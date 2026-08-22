from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from teaching_console.services.model_optimization_service import (
    ABComparisonService,
    BoundingBox,
    CandidateModelManager,
    CanvasImageTransform,
    ColabPackageBuilder,
    DataLeakageError,
    DatasetBuilder,
    HardFrameSelector,
    yolo_label,
    yolo_xywh,
)


class ModelOptimizationServiceTests(unittest.TestCase):
    def test_hard_frames_have_cap_deterministic_order_and_time_dedupe(self) -> None:
        rows = [{"frame_index": index, "time_seconds": index / 10, "system_count": index % 7, "confidences": [0.2], "flow_conflicts": index % 2} for index in range(80)]
        first = HardFrameSelector.select(rows, limit=25, min_time_gap_seconds=1.0)
        second = HardFrameSelector.select(rows, limit=25, min_time_gap_seconds=1.0)
        self.assertLessEqual(len(first), 25)
        self.assertEqual([(x.frame_index, x.score) for x in first], [(x.frame_index, x.score) for x in second])
        self.assertTrue(all(abs(a.time_seconds - b.time_seconds) >= 1.0 for index, a in enumerate(first) for b in first[index + 1:]))
        with self.assertRaises(ValueError):
            HardFrameSelector.select(rows, limit=26)

    def test_canvas_box_move_resize_and_yolo_label_use_original_coordinates(self) -> None:
        transform = CanvasImageTransform(1920, 1080, 100, 50, 960, 540)
        box = transform.canvas_box_to_image(196, 104, 580, 320)
        self.assertEqual(box, BoundingBox(192, 108, 960, 540))
        self.assertEqual(box.moved(2000, 0, 1920, 1080), BoundingBox(1152, 108, 1920, 540))
        self.assertEqual(box.resized("top_left", 0, 0, 1920, 1080), BoundingBox(0, 0, 960, 540))
        self.assertEqual(yolo_xywh(BoundingBox(0, 0, 960, 540), 1920, 1080), (0.25, 0.25, 0.5, 0.5))
        self.assertEqual(yolo_label(BoundingBox(0, 0, 960, 540), 1920, 1080), "0 0.250000 0.250000 0.500000 0.500000")
        with self.assertRaises(ValueError): yolo_label(box, 1920, 1080, class_id=1)

    def test_dataset_is_video_split_and_yolo_standard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame_a, frame_b = root / "a.jpg", root / "b.jpg"
            frame_a.write_bytes(b"a"); frame_b.write_bytes(b"b")
            rows = [
                {"source_video": "000327.mp4", "frame_path": frame_a, "frame_index": 10, "image_width": 100, "image_height": 50, "boxes": [BoundingBox(0, 0, 50, 25)]},
                {"source_video": "000345.mp4", "frame_path": frame_b, "frame_index": 20, "image_width": 100, "image_height": 50, "boxes": []},
            ]
            result = DatasetBuilder(root).build("huian_person_v1", rows, {"000327.mp4": "train", "000345.mp4": "test"})
            self.assertEqual((result.frame_count, result.annotation_count), (2, 1))
            self.assertTrue((result.dataset_dir / "images" / "train").is_dir())
            labels = list((result.dataset_dir / "labels" / "train").glob("*.txt"))
            self.assertEqual(labels[0].read_text(encoding="utf-8"), "0 0.250000 0.250000 0.500000 0.500000\n")
            self.assertIn("  0: person", (result.dataset_dir / "data.yaml").read_text(encoding="utf-8"))
            metadata = json.loads((result.dataset_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["split_assignment"]["000327.mp4"], "train")
            conflict = [dict(rows[0], split="train"), dict(rows[0], split="test", frame_index=11)]
            with self.assertRaises(DataLeakageError):
                DatasetBuilder(root).build("leak", conflict, {"000327.mp4": "train"})

    def test_colab_package_and_candidate_import_never_touch_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "training").mkdir(); (root / "models").mkdir()
            # Copy the project's editable true training script, without executing it.
            source_train = Path(__file__).resolve().parents[2] / "training" / "train.py"
            (root / "training" / "train.py").write_text(source_train.read_text(encoding="utf-8"), encoding="utf-8")
            baseline = root / "models" / "yolov8n.pt"; baseline.write_bytes(b"baseline")
            frame = root / "frame.jpg"; frame.write_bytes(b"frame")
            dataset = DatasetBuilder(root).build("huian_person_v1", [{"source_video": "v.mp4", "frame_path": frame, "frame_index": 1, "image_width": 10, "image_height": 10, "boxes": []}], {"v.mp4": "test"}).dataset_dir
            package = ColabPackageBuilder(root).build(dataset, "huian_person_v1")
            self.assertTrue(all(path.is_file() for path in (package.dataset_zip, package.notebook, package.train_script, package.package_dir / "data.yaml", package.package_dir / "README.md")))
            self.assertIn('DEFAULT_MODEL = "yolov8n.pt"', package.train_script.read_text(encoding="utf-8"))
            self.assertIn("model.train(", package.train_script.read_text(encoding="utf-8"))
            with zipfile.ZipFile(package.dataset_zip) as archive: self.assertIn("dataset/data.yaml", archive.namelist())
            source_best = root / "downloaded_best.pt"; source_best.write_bytes(b"candidate")
            imported = CandidateModelManager(root).import_best_pt("huian_person_v1", source_best)
            self.assertEqual(baseline.read_bytes(), b"baseline")
            self.assertEqual(imported.model_path.read_bytes(), b"candidate")
            self.assertEqual(json.loads(imported.metadata_path.read_text(encoding="utf-8"))["base_model"], "yolov8n.pt")

    def test_ab_metrics_use_exact_same_ground_truth(self) -> None:
        gt = [{"frame_id": "test-f1", "boxes": [BoundingBox(0, 0, 10, 10), BoundingBox(20, 0, 30, 10)]}]
        result = ABComparisonService().compare(gt, {"test-f1": [BoundingBox(0, 0, 10, 10)]}, {"test-f1": [BoundingBox(0, 0, 10, 10), BoundingBox(20, 0, 30, 10)]})
        self.assertEqual(result["ground_truth_frame_ids"], ["test-f1"])
        self.assertEqual(result["baseline"]["count_mae"], 1.0)
        self.assertEqual(result["candidate"]["count_mae"], 0.0)
        self.assertEqual(result["candidate"]["precision"], 1.0)
        self.assertEqual(result["candidate"]["recall"], 1.0)
        self.assertIsNone(result["candidate"]["map50"])


if __name__ == "__main__":
    unittest.main()
