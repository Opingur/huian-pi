from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from teaching_console.pages.research_page import experiment_list_rows
from teaching_console.services.research_store import ResearchStore


class ExperimentListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.store = ResearchStore(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def test_list_rows_are_child_friendly_and_newest_first(self) -> None:
        old = self.store.create_experiment("课堂案例", r"C:\video\000327.mp4", "teaching")
        self.store.create_count_annotation(old, 1, 1, 15, 2)
        new = self.store.create_experiment("学校楼道", r"D:\record\stair01.mp4", "formal")
        self.store.create_count_annotation(new, 1, 1, 15, 3)
        self.store.update_ground_truth(new, 1, 3)
        rows = experiment_list_rows(self.store)
        self.assertEqual(rows[0]["id"], new)
        self.assertEqual(rows[0]["type"], "正式研究")
        self.assertEqual(rows[1]["type"], "教学练习")
        self.assertEqual(rows[0]["video"], "stair01.mp4")
        self.assertEqual((rows[0]["progress"], rows[1]["progress"]), ("1 / 1", "0 / 1"))

    def test_empty_store_has_no_rows(self) -> None:
        self.assertEqual(experiment_list_rows(self.store), [])


if __name__ == "__main__":
    unittest.main()
