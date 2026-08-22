"""Regression tests for child-level Source Map teaching details."""
from __future__ import annotations

import unittest

from teaching_console.project_paths import project_root
from teaching_console.services.source_map_catalog import entry_exists, teaching_entries


class SourceMapLessonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = project_root()
        cls.entries = teaching_entries(cls.root)
        cls.by_id = {entry.id: entry for entry in cls.entries}

    @staticmethod
    def _fingerprint(entry) -> tuple[object, ...]:
        return (
            entry.question, entry.summary, entry.concepts, entry.teaching_file,
            entry.inputs, entry.outputs, entry.config, entry.note,
            entry.lesson_upstream, entry.lesson_downstream,
        )

    def test_child_ids_are_unique(self) -> None:
        self.assertEqual(len(self.entries), len(self.by_id))

    def test_d1_children_have_distinct_teaching_details(self) -> None:
        children = [self.by_id[f"lesson.01.{index}"] for index in range(1, 7)]
        self.assertEqual(len(children), len({self._fingerprint(entry) for entry in children}))
        frame_info = self.by_id["lesson.01.5"]
        self.assertIn("shape", frame_info.concepts)
        self.assertEqual("—", frame_info.config)
        self.assertNotIn("Picamera2", frame_info.concepts)
        self.assertIn("Picamera2", self.by_id["lesson.01.6"].concepts)

    def test_yolo_and_tracking_children_are_not_title_only_copies(self) -> None:
        for section, count in (("02", 10), ("03", 8)):
            with self.subTest(section=section):
                children = [self.by_id[f"lesson.{section}.{index}"] for index in range(1, count + 1)]
                self.assertEqual(len(children), len({self._fingerprint(entry) for entry in children}))
        self.assertIn("Track ID", self.by_id["lesson.03.4"].note)
        self.assertIn("置信", self.by_id["lesson.02.6"].summary)

    def test_d1_teaching_files_and_official_paths_exist(self) -> None:
        for entry_id in ("lesson.01.1", "lesson.01.4", "lesson.01.5", "lesson.02.1", "lesson.02.9"):
            entry = self.by_id[entry_id]
            self.assertTrue((self.root / entry.teaching_file).is_file(), entry.teaching_file)
            self.assertTrue(entry_exists(self.root, entry), entry.path)


if __name__ == "__main__":
    unittest.main()
