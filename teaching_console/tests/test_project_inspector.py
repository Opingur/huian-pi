"""Non-GUI contract tests for the teaching Source Map facts."""
from __future__ import annotations

import unittest

from teaching_console.project_paths import project_root
from teaching_console.services.project_inspector import (
    entry_exists,
    search_entries,
    source_entries,
)


class ProjectInspectorTests(unittest.TestCase):
    """Keep the static teaching map connected to real project source files."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = project_root()
        cls.entries = source_entries(cls.root)
        cls.entries_by_id = {entry.id: entry for entry in cls.entries}

    def test_all_official_entries_reference_existing_paths(self) -> None:
        official_entries = [entry for entry in self.entries if entry.status == "official"]

        self.assertTrue(official_entries, "Source Map should contain official entries")
        missing = [entry.path for entry in official_entries if not entry_exists(self.root, entry)]
        self.assertEqual([], missing, f"official Source Map paths missing: {missing}")

    def test_esp32_candidate_stays_inactive(self) -> None:
        candidate = self.entries_by_id["esp32_candidate"]

        self.assertEqual("inactive", candidate.status)
        self.assertTrue(entry_exists(self.root, candidate))

    def test_all_declared_upstream_and_downstream_links_are_known_nodes(self) -> None:
        known_ids = set(self.entries_by_id)
        for entry in self.entries:
            with self.subTest(node=entry.id):
                self.assertTrue(set(entry.upstream).issubset(known_ids))
                self.assertTrue(set(entry.downstream).issubset(known_ids))

    def test_core_data_chain_has_expected_direction(self) -> None:
        """Assert the verified hand-offs rather than a guessed single linear chain."""
        edges = (
            ("camera_frame", "yolo_detection"),
            ("yolo_detection", "bytetrack_tracking"),
            ("bytetrack_tracking", "people_flow"),
            ("bytetrack_tracking", "trajectory_history"),
            ("people_flow", "prediction"),
            ("prediction", "flow_risk"),
            ("trajectory_history", "motion_direction"),
            ("motion_direction", "flow_groups"),
            ("flow_groups", "flow_risk"),
            ("flow_risk", "crowd_index"),
            ("crowd_index", "vision_risk"),
            ("vision_risk", "uart_json"),
            ("uart_json", "esp32_firmware"),
        )

        for upstream, downstream in edges:
            with self.subTest(upstream=upstream, downstream=downstream):
                self.assertIn(upstream, self.entries_by_id)
                self.assertIn(downstream, self.entries_by_id)
                self.assertIn(downstream, self.entries_by_id[upstream].downstream)
                self.assertIn(upstream, self.entries_by_id[downstream].upstream)

    def test_search_finds_the_main_classroom_concepts(self) -> None:
        expected_nodes = {
            "YOLO": "yolo_detection",
            "person": "yolo_detection",
            "Track ID": "bytetrack_tracking",
            "轨迹": "trajectory_history",
            "方向": "motion_direction",
            "Crowd Index": "crowd_index",
            "预测": "prediction",
            "UART": "uart_json",
            "MQ-2": "esp32_firmware",
            "DHT11": "esp32_firmware",
            "RGB": "esp32_firmware",
            "蜂鸣器": "esp32_firmware",
            "Ground Truth": "validation",
            "MAE": "validation",
        }

        for query, expected_node_id in expected_nodes.items():
            with self.subTest(query=query):
                found_ids = {entry.id for entry in search_entries(self.root, query)}
                self.assertIn(expected_node_id, found_ids)


if __name__ == "__main__":
    unittest.main()
