from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from teaching_console.services.research_count_service import ResearchCountService
from teaching_console.services.research_store import ResearchStore


class ExportNameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.store = ResearchStore(self.root)
        self.service = ResearchCountService(self.store)
        self.exports = self.root / "validation" / "exports"

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def create(self, name: str) -> str:
        return self.store.create_experiment(name, "raw.mp4", "teaching")

    def test_name_is_stable_and_windows_safe(self) -> None:
        experiment_id = self.create('  000327: GT?  ')
        first = self.service.export_experiment(experiment_id, self.exports)
        second = self.service.export_experiment(experiment_id, self.exports)
        self.assertEqual((first.name, first), ("000327_ GT_", second))
        self.assertEqual(__import__("json").loads((first / "experiment_summary.json").read_text(encoding="utf-8"))["experiment"]["id"], experiment_id)

    def test_same_name_is_isolated_and_empty_falls_back_to_id(self) -> None:
        first_id, second_id = self.create("学校楼道实验"), self.create("学校楼道实验")
        first, second = self.service.export_experiment(first_id, self.exports), self.service.export_experiment(second_id, self.exports)
        self.assertEqual(first.name, "学校楼道实验")
        self.assertEqual(second.name, f"学校楼道实验_{second_id[:8]}")
        with self.store._connection() as connection:
            connection.execute("UPDATE experiments SET name = '' WHERE id = ?", (first_id,))
        self.assertEqual(self.service.export_experiment(first_id, self.exports).name, first_id)


if __name__ == "__main__":
    unittest.main()
