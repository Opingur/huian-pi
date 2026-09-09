import unittest
from unittest.mock import patch

import numpy as np

from ui.dashboard_layout import CANVAS_WIDTH, draw_dashboard
from ui.flow_group_visualizer import draw_flow_tracks


class RunningVisualCueTests(unittest.TestCase):
    def test_running_target_uses_a_thick_red_box(self):
        image = np.zeros((120, 160, 3), dtype=np.uint8)
        detections = [{"track_id": 7, "x1": 20, "y1": 25, "x2": 80, "y2": 105}]
        motions = {7: {"running": True, "motion_state": "MOVING", "trail": [], "heading_angle": 0.0}}
        with patch("ui.flow_group_visualizer.cv2.rectangle") as rectangle:
            draw_flow_tracks(image, detections, motions, {"show_boxes": True, "show_track_id": False}, {}, [])
        self.assertIn(((20, 25), (80, 105), (60, 60, 235), 5), [call.args[1:] for call in rectangle.call_args_list])

    def test_running_event_flashes_an_orange_dashboard_edge(self):
        frame = np.full((720, 1280, 3), (32, 64, 96), dtype=np.uint8)
        status = {"vision_risk": "NORMAL", "visual_alarm": "NONE", "running_event": True, "running_count": 1, "source_time": 0.0}
        context = {"motions": {}, "flow_groups": {}, "fire_detections": [], "prediction_history": [], "esp32_status": None, "esp32_status_stale": True, "esp32_configured": False}
        flash_on = draw_dashboard(frame, [], status, display={"mode": "live"}, ui_context=context)
        flash_off = draw_dashboard(frame, [], {**status, "source_time": 0.31}, display={"mode": "live"}, ui_context=context)
        self.assertEqual(flash_on[3, CANVAS_WIDTH // 2].tolist(), [0, 150, 255])
        self.assertEqual(flash_off[3, CANVAS_WIDTH // 2].tolist(), frame[3, CANVAS_WIDTH // 2].tolist())


if __name__ == "__main__":
    unittest.main()
