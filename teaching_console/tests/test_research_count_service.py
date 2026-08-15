from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from teaching_console.services.research_count_service import ResearchCountService, build_sample_tasks
from teaching_console.services.research_store import ResearchStore


class CountServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.store = ResearchStore(self.root)
        self.experiment_id = self.store.create_experiment("E", "raw.mp4", "teaching")
        self.service = ResearchCountService(self.store)

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_default_samples_are_uniform_idempotent_and_restored(self) -> None:
        tasks = self.service.generate_tasks(self.experiment_id, 60, 15)
        self.assertEqual(len(tasks), 25)
        self.assertEqual(tasks, self.service.generate_tasks(self.experiment_id, 60, 15))
        self.assertTrue(all(a["video_time_seconds"] < b["video_time_seconds"] for a, b in zip(tasks, tasks[1:])))
        self.assertEqual(tasks[4]["frame_index"], round(tasks[4]["video_time_seconds"] * 15))
        self.assertEqual(len(ResearchStore(self.root).annotations(self.experiment_id)), 25)

    def test_key_sample_count_backfill_metrics_and_export(self) -> None:
        self.service.generate_tasks(self.experiment_id, 60, 15)
        self.assertIsNotNone(self.service.add_key_sample(self.experiment_id, 31.23, 15, note="峰值"))
        self.assertIsNone(self.service.add_key_sample(self.experiment_id, 31.28, 15))
        rows = self.store.annotations(self.experiment_id)
        self.store.update_ground_truth(self.experiment_id, 1, 4)
        self.assertEqual(self.service.metrics(self.experiment_id)["mae"], None)
        self.store.update_system_count(rows[0]["id"], 5)
        self.assertEqual(self.store.annotations(self.experiment_id)[0]["absolute_error"], 1.0)
        self.store.create_count_annotation(self.experiment_id, 99, 58, 870, 4)
        self.store.update_ground_truth(self.experiment_id, 99, 4)
        metrics = self.service.metrics(self.experiment_id)
        self.assertEqual((metrics["evaluated_samples"], metrics["mae"], metrics["max_absolute_error"], metrics["exact_match_rate"]), (2, 0.5, 1.0, 0.5))
        output = self.service.export_experiment(self.experiment_id, self.root / "exports")
        self.assertEqual(len((output / "count_ground_truth.csv").read_text(encoding="utf-8-sig").splitlines()), 28)
        self.assertEqual(json.loads((output / "experiment_summary.json").read_text(encoding="utf-8"))["metrics"]["mae"], 0.5)

    def test_sampling_never_enumerates_frames(self) -> None:
        self.assertEqual(len(build_sample_tasks(60, 15)), 25)
        self.assertLessEqual(len(build_sample_tasks(3600, 15)), 30)


if __name__ == "__main__":
    unittest.main()
