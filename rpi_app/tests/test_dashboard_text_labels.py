import inspect
import unittest

import numpy as np

from ui import dashboard_layout
from ui.flow_group_visualizer import draw_flow_legend


class DashboardTextLabelTests(unittest.TestCase):
    def test_dashboard_has_no_visual_smoke_row_but_keeps_mq2_smoke(self):
        rows = dashboard_layout._environment_rows(
            {}, {"esp32_status": None, "esp32_status_stale": True, "esp32_configured": False, "fire_detections": []}
        )
        labels = [label for label, _value, _color in rows]
        self.assertIn("视觉火焰", labels)
        self.assertIn("MQ-2烟雾", labels)
        self.assertNotIn("视觉烟雾", labels)

    def test_top_visual_fire_text_has_no_smoke_phrase(self):
        source = inspect.getsource(dashboard_layout._top_fire_text)
        self.assertNotIn("烟雾", source)
        self.assertIn("已发现火焰", source)
        self.assertIn("疑似火焰", source)

    def test_time_tick_source_uses_ascii_numbers_and_signs(self):
        source = inspect.getsource(dashboard_layout._draw_live_trend)
        for label in ("-15\\u79d2", "-10\\u79d2", "-5\\u79d2", "\\u73b0\\u5728", "+10\\u79d2", "+20\\u79d2", "+30\\u79d2"):
            self.assertIn(label, source)

    def test_flow_legend_uses_existing_letter_labels(self):
        image = np.zeros((100, 160, 3), dtype=np.uint8)
        entries = []
        groups = {
            0: {"label": "A", "color": (1, 2, 3)},
            1: {"label": "B", "color": (4, 5, 6)},
            2: {"label": "C", "color": (7, 8, 9)},
        }
        draw_flow_legend(image, groups, entries)
        self.assertEqual([entry[1] for entry in entries], ["A流", "B流", "C流"])

    def test_no_active_flow_has_no_zero_flow_label(self):
        image = np.zeros((100, 160, 3), dtype=np.uint8)
        entries = []
        draw_flow_legend(image, {}, entries)
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()