from __future__ import annotations

import unittest
import sqlite3
import shutil
import tempfile
from pathlib import Path

from teaching_console.services.ai_growth_experiment_service import (
    CHILD_DIFFICULTY_REASONS,
    challenge_feedback_rows,
    required_split_message,
    split_label,
    summarize_growth,
)
from teaching_console.services.research_store import ResearchStore


class AIGrowthExperimentServiceTests(unittest.TestCase):
    def test_child_reasons_and_split_labels_are_stable(self) -> None:
        self.assertEqual(
            CHILD_DIFFICULTY_REASONS,
            ("人太多重叠", "画面太暗", "人离得太远", "有人被遮挡"),
        )
        self.assertEqual(split_label("test"), "小测图片（AI 从没见过）")

    def test_missing_split_message_requires_independent_challenge_video(self) -> None:
        message = required_split_message({"learn.mp4": "train", "check.mp4": "val"})
        self.assertIn("小测图片", message)
        self.assertIsNone(required_split_message({"learn.mp4": "train", "check.mp4": "val", "challenge.mp4": "test"}))

    def test_growth_summary_only_calls_a_real_reduction_an_improvement(self) -> None:
        improved = summarize_growth({"baseline": {"count_mae": 3.0}, "candidate": {"count_mae": 1.25}})
        self.assertEqual(improved.improvement, 1.75)
        self.assertIn("AI 进步了", improved.message)

        worse = summarize_growth({"baseline": {"count_mae": 1.0}, "candidate": {"count_mae": 2.0}})
        self.assertLess(worse.improvement, 0)
        self.assertIn("没有进步", worse.message)

    def test_challenge_rows_explain_each_real_shared_gt_sample(self) -> None:
        rows = challenge_feedback_rows(({
            "frame_id": "challenge.mp4:20",
            "ground_truth_count": 10,
            "baseline": {"model_count": 7, "absolute_count_error": 3},
            "candidate": {"model_count": 9, "absolute_count_error": 1},
        },))
        self.assertEqual((rows[0].baseline_count, rows[0].candidate_count), (7, 9))
        self.assertEqual(rows[0].improvement, 2)
        self.assertEqual(rows[0].message, "少数错 2 人")


    def test_completed_box_annotation_and_child_reason_are_persisted(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        store = ResearchStore(root)
        project_id = store.create_detection_annotation_project("学习图片", "learn.mp4", "train", "huian_person_v1")
        frame_id = store.create_detection_frame_annotation(project_id, 12, 0.8, 640, 480)
        store.update_detection_frame_annotation(
            frame_id, student_reason="有人被遮挡", annotation_completed=True
        )
        frame = store.get_detection_frame_annotation(frame_id)
        self.assertEqual(frame["student_reason"], "有人被遮挡")
        self.assertEqual(frame["annotation_completed"], 1)

    def test_legacy_detection_frame_gets_new_columns_without_losing_box(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        database = root / "legacy.sqlite3"
        with sqlite3.connect(database) as connection:
            connection.executescript(
                "CREATE TABLE detection_frame_annotations ("
                "id TEXT PRIMARY KEY, project_id TEXT, source_video TEXT, frame_index INTEGER, "
                "video_time_seconds REAL, image_path TEXT, image_width INTEGER, image_height INTEGER, "
                "system_count INTEGER, average_confidence REAL, minimum_confidence REAL, "
                "recommendation_reasons TEXT, kept INTEGER, created_at TEXT, updated_at TEXT);"
                "CREATE TABLE detection_person_boxes (id TEXT PRIMARY KEY, frame_annotation_id TEXT, "
                "class_id INTEGER, x1 REAL, y1 REAL, x2 REAL, y2 REAL, created_at TEXT, updated_at TEXT);"
                "INSERT INTO detection_frame_annotations VALUES ('f', 'p', 'old.mp4', 1, 0.1, NULL, 640, 480, 2, NULL, NULL, '', 1, 'now', 'now');"
                "INSERT INTO detection_person_boxes VALUES ('b', 'f', 0, 1, 1, 2, 2, 'now', 'now');"
            )
            ResearchStore._migrate_detection_annotation_columns(connection)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(detection_frame_annotations)")}
            row = connection.execute("SELECT annotation_completed FROM detection_frame_annotations WHERE id = 'f'").fetchone()
        self.assertTrue({"student_reason", "annotation_completed"}.issubset(columns))
        self.assertEqual(row[0], 1)
if __name__ == "__main__":
    unittest.main()
