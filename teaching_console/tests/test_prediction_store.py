from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from teaching_console.services.research_store import ResearchStore


class PredictionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.store = ResearchStore(self.root)
        self.experiment_id = self.store.create_experiment("预测实验", "raw.mp4", "formal")

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_schema_and_frozen_predictions(self) -> None:
        with sqlite3.connect(self.store.database_path) as connection:
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(names, {"experiments", "count_annotations", "prediction_annotations"})
        item_id = self.store.create_prediction_annotation(self.experiment_id, 20.0, 300, 10, 0.3, 13.0, 16.0, 19.0)
        self.store.update_prediction_ground_truth(item_id, 10, 12)
        self.store.update_prediction_ground_truth(item_id, 20, 15)
        self.store.update_prediction_ground_truth(item_id, 30, 19)
        item = self.store.prediction_annotations(self.experiment_id)[0]
        self.assertEqual((item["prediction_10"], item["prediction_20"], item["prediction_30"]), (13.0, 16.0, 19.0))
        self.assertEqual((item["gt_10"], item["error_10"], item["error_20"], item["error_30"]), (12, 1.0, 1.0, 0.0))
        self.store.update_prediction_ground_truth(item_id, 10, 11)
        item = self.store.prediction_annotations(self.experiment_id)[0]
        self.assertEqual((item["prediction_10"], item["gt_10"], item["error_10"]), (13.0, 11, 2.0))

    def test_upgrade_preserves_existing_count_data(self) -> None:
        legacy_root = Path(tempfile.mkdtemp())
        database = legacy_root / "validation" / "research_data" / "huian_research.sqlite3"; database.parent.mkdir(parents=True)
        connection = sqlite3.connect(database)
        try:
            connection.executescript("CREATE TABLE experiments (id TEXT PRIMARY KEY, name TEXT, video_path TEXT, experiment_type TEXT, description TEXT, created_at TEXT, git_commit TEXT); CREATE TABLE count_annotations (id TEXT PRIMARY KEY, experiment_id TEXT, sample_index INTEGER, video_time_seconds REAL, frame_index INTEGER, system_count INTEGER, ground_truth_count INTEGER, absolute_error REAL, note TEXT, created_at TEXT, updated_at TEXT);")
            connection.execute("INSERT INTO experiments VALUES ('e', '旧实验', 'v', 'teaching', '', 'now', NULL)")
            connection.execute("INSERT INTO count_annotations VALUES ('c', 'e', 1, 1, 15, 2, 2, 0, '', 'now', 'now')")
            connection.commit()
        finally:
            connection.close()
        upgraded = ResearchStore(legacy_root)
        self.assertEqual(upgraded.annotations("e")[0]["ground_truth_count"], 2)
        self.assertEqual(len(upgraded.prediction_annotations("e")), 0)
        shutil.rmtree(legacy_root)


if __name__ == "__main__":
    unittest.main()
