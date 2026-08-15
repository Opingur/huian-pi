from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from teaching_console.services.research_prediction_service import ResearchPredictionService
from teaching_console.services.research_store import ResearchStore


def timeline():
    return [
        {"time_seconds": time, "frame_index": int(time * 15), "current_system_count": 6 + index,
         "prediction_slope": 0.2, "prediction_10": 8 + index, "prediction_20": 10 + index, "prediction_30": 12 + index}
        for index, time in enumerate((10, 20, 30, 40, 50, 60, 80))
    ] + [{"time_seconds": 25, "frame_index": 375, "current_system_count": 1, "prediction_slope": None, "prediction_10": None, "prediction_20": None, "prediction_30": None}]


class PredictionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()); self.store = ResearchStore(self.root)
        self.experiment_id = self.store.create_experiment("预测", "raw.mp4", "formal")
        self.service = ResearchPredictionService(self.store)

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_anchor_selection_is_valid_ordered_and_idempotent(self) -> None:
        anchors = self.service.generate_anchors(self.experiment_id, timeline(), 90)
        self.assertEqual(len(anchors), 5)
        self.assertTrue(all(row["anchor_time_seconds"] + 30 <= 90 for row in anchors))
        self.assertEqual([row["anchor_time_seconds"] for row in anchors], sorted(row["anchor_time_seconds"] for row in anchors))
        self.assertEqual(anchors, self.service.generate_anchors(self.experiment_id, timeline(), 90))

    def test_gt_reference_metrics_and_export(self) -> None:
        anchor = self.service.generate_anchors(self.experiment_id, timeline(), 90)[0]
        self.store.create_count_annotation(self.experiment_id, 1, anchor["anchor_time_seconds"] + 10.05, 0, 99)
        self.store.update_ground_truth(self.experiment_id, 1, 7)
        self.assertEqual(self.service.apply_existing_count_gt(anchor["id"], 10), 7)
        self.assertIsNone(self.service.find_existing_count_ground_truth(self.experiment_id, anchor["anchor_time_seconds"] + 20))
        self.service.save_prediction_gt(anchor["id"], 20, 9); self.service.save_prediction_gt(anchor["id"], 30, 12)
        item = self.store.prediction_annotations(self.experiment_id)[0]
        self.assertEqual((item["prediction_10"], item["gt_10"], item["error_10"]), (8.0, 7, 1.0))
        self.service.save_prediction_gt(anchor["id"], 10, 6)
        self.assertEqual(self.store.prediction_annotations(self.experiment_id)[0]["prediction_10"], 8.0)
        metrics = self.service.prediction_metrics(self.experiment_id)
        self.assertEqual((metrics["completed_prediction_count"], metrics["samples_10"], metrics["mae_10"], metrics["mae_20"], metrics["mae_30"]), (1, 1, 2.0, 1.0, 0.0))
        output = self.service.export_experiment(self.experiment_id, self.root / "exports")
        self.assertTrue((output / "prediction_ground_truth.csv").is_file())
        self.assertEqual(json.loads((output / "experiment_summary.json").read_text(encoding="utf-8"))["prediction_metrics"]["mae_10"], 2.0)

    def test_invalid_input_and_empty_metrics(self) -> None:
        self.assertEqual(self.service.prediction_metrics(self.experiment_id)["mae_10"], None)
        item = self.service.generate_anchors(self.experiment_id, timeline(), 40)[0]
        with self.assertRaises(ValueError): self.service.save_prediction_gt(item["id"], 5, 1)
        with self.assertRaises(ValueError): self.service.save_prediction_gt(item["id"], 10, -1)
        self.store.create_count_annotation(self.experiment_id, 8, item["anchor_time_seconds"] + 10, 0, 12)
        self.assertIsNone(self.service.apply_existing_count_gt(item["id"], 10))


if __name__ == "__main__":
    unittest.main()
