from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from teaching_console.services.research_store import ResearchStore


class OptimizationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.store = ResearchStore(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_new_tables_are_added_without_changing_research_tables(self) -> None:
        with sqlite3.connect(self.store.database_path) as connection:
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue(
            {
                "experiments",
                "count_annotations",
                "prediction_annotations",
                "detection_annotation_projects",
                "detection_frame_annotations",
                "detection_person_boxes",
                "model_experiments",
                "model_deployments",
            }.issubset(names)
        )

    def test_legacy_count_prediction_database_is_opened_without_data_loss(self) -> None:
        legacy_root = Path(tempfile.mkdtemp())
        database = legacy_root / "validation" / "research_data" / "huian_research.sqlite3"
        database.parent.mkdir(parents=True)
        connection = sqlite3.connect(database)
        try:
            connection.executescript(
                "CREATE TABLE experiments (id TEXT PRIMARY KEY, name TEXT, video_path TEXT, experiment_type TEXT, description TEXT, created_at TEXT, git_commit TEXT);"
                "CREATE TABLE count_annotations (id TEXT PRIMARY KEY, experiment_id TEXT, sample_index INTEGER, video_time_seconds REAL, frame_index INTEGER, system_count INTEGER, ground_truth_count INTEGER, absolute_error REAL, note TEXT, created_at TEXT, updated_at TEXT);"
                "CREATE TABLE prediction_annotations (id TEXT PRIMARY KEY, experiment_id TEXT, anchor_time_seconds REAL, anchor_frame_index INTEGER, current_system_count INTEGER, prediction_slope REAL, prediction_10 REAL, prediction_20 REAL, prediction_30 REAL, gt_10 INTEGER, gt_20 INTEGER, gt_30 INTEGER, error_10 REAL, error_20 REAL, error_30 REAL, note TEXT, created_at TEXT, updated_at TEXT);"
            )
            connection.execute("INSERT INTO experiments VALUES ('e', '旧实验', 'old.mp4', 'teaching', '', 'now', NULL)")
            connection.execute("INSERT INTO count_annotations VALUES ('c', 'e', 1, 1.0, 15, 2, 2, 0.0, '', 'now', 'now')")
            connection.commit()
        finally:
            connection.close()
        try:
            upgraded = ResearchStore(legacy_root)
            self.assertEqual(upgraded.annotations("e")[0]["ground_truth_count"], 2)
            self.assertEqual(upgraded.prediction_annotations("e"), [])
            self.assertEqual(upgraded.list_detection_annotation_projects(), [])
        finally:
            shutil.rmtree(legacy_root)

    def test_detection_project_frames_and_raw_person_boxes_crud(self) -> None:
        project_id = self.store.create_detection_annotation_project(
            "000327 困难帧", "test_data/000327.mp4", "train", "huian_person_v1"
        )
        frame_id = self.store.create_detection_frame_annotation(
            project_id,
            120,
            8.0,
            1920,
            1080,
            image_path="validation/frames/000327_120.jpg",
            system_count=8,
            average_confidence=0.72,
            minimum_confidence=0.31,
            recommendation_reasons="多人遮挡；检测人数跳变",
        )
        box_id = self.store.create_detection_person_box(frame_id, 100, 80, 260, 500)
        self.store.update_detection_person_box(box_id, 110, 90, 270, 510)
        boxes = self.store.detection_person_boxes(frame_id)
        self.assertEqual((boxes[0]["class_id"], boxes[0]["x1"], boxes[0]["y2"]), (0, 110.0, 510.0))
        self.store.replace_detection_person_boxes(
            frame_id,
            [
                {"x1": 1, "y1": 2, "x2": 11, "y2": 22},
                {"class_id": 0, "x1": 30, "y1": 40, "x2": 70, "y2": 90},
            ],
        )
        self.assertEqual(len(self.store.detection_person_boxes(frame_id)), 2)
        self.store.update_detection_frame_annotation(frame_id, kept=False)
        self.assertEqual(len(self.store.detection_frame_annotations(project_id)), 1)
        self.assertEqual(self.store.detection_frame_annotations(project_id, include_skipped=False), [])
        with self.assertRaises(ValueError):
            self.store.create_detection_person_box(frame_id, 0, 0, 10, 10, class_id=1)
        with self.assertRaises(ValueError):
            self.store.create_detection_person_box(frame_id, 10, 10, 10, 20)

    def test_video_level_split_and_model_candidate_deployment_rollback_records(self) -> None:
        project_id = self.store.create_detection_annotation_project("视频", "raw.mp4", "unassigned")
        self.store.update_detection_annotation_project(project_id, split_name="test", status="ready")
        project = self.store.get_detection_annotation_project(project_id)
        self.assertEqual((project["source_video"], project["split_name"], project["status"]), ("raw.mp4", "test", "ready"))
        with self.assertRaises(ValueError):
            self.store.update_detection_annotation_project(project_id, split_name="frame_random")
        self.store.create_detection_annotation_project("同源 train", "same.mp4", "train", "leak_check")
        self.store.create_detection_annotation_project("同源 test", "same.mp4", "test", "leak_check")
        with self.assertRaises(ValueError):
            self.store.validate_detection_dataset_splits("leak_check")

        experiment_id = self.store.create_model_experiment(
            "huian_person_v1 微调", "huian_person_v1", "models/yolov8n.pt", epochs=50, imgsz=640
        )
        self.store.set_model_candidate(experiment_id, "models/experiments/huian_person_v1/best.pt", result_metadata_path="result_metadata.json")
        self.store.set_model_candidate_state(experiment_id, "accepted")
        experiment = self.store.get_model_experiment(experiment_id)
        self.assertEqual((experiment["candidate_state"], experiment["candidate_model_path"]), ("accepted", "models/experiments/huian_person_v1/best.pt"))

        deployment_id = self.store.create_model_deployment(
            experiment_id,
            "huian-pi",
            "/home/x/Huian_YOLO",
            "models/huian_person_v1.pt",
            previous_model_path="models/yolov8n.pt",
            previous_config_value="models/yolov8n.pt",
        )
        self.store.update_model_deployment(deployment_id, status="deployed")
        self.store.mark_model_deployment_rolled_back(deployment_id)
        deployment = self.store.model_deployments(experiment_id)[0]
        self.assertEqual(
            (deployment["previous_model_path"], deployment["status"], deployment["rollback_status"]),
            ("models/yolov8n.pt", "rolled_back", "completed"),
        )

    def test_store_connections_close_after_optimization_operations(self) -> None:
        project_id = self.store.create_detection_annotation_project("锁测试", "raw.mp4")
        frame_id = self.store.create_detection_frame_annotation(project_id, 1, 0.1, 640, 480)
        self.store.create_detection_person_box(frame_id, 1, 1, 10, 10)
        shutil.rmtree(self.root)
        self.assertFalse(self.root.exists())
        self.root = Path(tempfile.mkdtemp())
        self.store = ResearchStore(self.root)


if __name__ == "__main__":
    unittest.main()
