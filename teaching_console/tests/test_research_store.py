from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from teaching_console.services.research_store import ResearchStore


class ResearchStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.store = ResearchStore(self.temp_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def test_initializes_exactly_two_tables(self) -> None:
        import sqlite3
        with sqlite3.connect(self.store.database_path) as connection:
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue({"experiments", "count_annotations", "prediction_annotations"}.issubset(names))

    def test_creates_and_reads_experiment(self) -> None:
        experiment_id = self.store.create_experiment("课堂练习", "raw.mp4", "teaching", "走廊场景")
        experiment = self.store.get_experiment(experiment_id)
        self.assertEqual(experiment["name"], "课堂练习")
        self.assertEqual(experiment["video_path"], "raw.mp4")
        self.assertEqual(len(self.store.list_experiments()), 1)

    def test_git_failures_do_not_block_experiment_creation(self) -> None:
        failures = (FileNotFoundError(), OSError(), subprocess.CalledProcessError(1, "git"))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch(
                "teaching_console.services.research_store.subprocess.check_output", side_effect=failure
            ):
                experiment_id = self.store.create_experiment("E", "v.mp4", "formal")
                self.assertIsNone(self.store.get_experiment(experiment_id)["git_commit"])

    def test_pending_annotation_can_be_completed_and_changed(self) -> None:
        experiment_id = self.store.create_experiment("E", "v.mp4", "teaching")
        self.store.create_count_annotation(experiment_id, 1, 24.0, 360, 12)
        annotation = self.store.annotations(experiment_id)[0]
        self.assertIsNone(annotation["ground_truth_count"])
        self.assertEqual(self.store.progress(experiment_id), (0, 1))
        self.store.update_ground_truth(experiment_id, 1, 11, "遮挡")
        self.store.update_ground_truth(experiment_id, 1, 10, "复核")
        annotation = self.store.annotations(experiment_id)[0]
        self.assertEqual((annotation["ground_truth_count"], annotation["absolute_error"], annotation["note"]), (10, 2.0, "复核"))
        self.assertEqual(self.store.progress(experiment_id), (1, 1))

    def test_connections_close_so_windows_can_delete_directory(self) -> None:
        database_path = self.store.database_path
        self.store.create_experiment("E", "v.mp4", "teaching")
        self.assertTrue(database_path.exists())
        shutil.rmtree(self.temp_dir)
        self.assertFalse(self.temp_dir.exists())
        self.temp_dir = Path(tempfile.mkdtemp())
        self.store = ResearchStore(self.temp_dir)


if __name__ == "__main__":
    unittest.main()
