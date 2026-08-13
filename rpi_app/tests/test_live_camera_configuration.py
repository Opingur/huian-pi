import json
import unittest
from pathlib import Path
from unittest.mock import patch

from vision.camera_runner import _configure_live_window


ROOT = Path(__file__).resolve().parents[2]


class LiveCameraConfigurationTests(unittest.TestCase):
    def test_fullscreen_window_uses_plain_highgui_path(self):
        with patch("vision.camera_runner.cv2.namedWindow") as named, patch("vision.camera_runner.cv2.setWindowProperty") as fullscreen:
            window = _configure_live_window({"display_window": True, "display": {"window_name": "Huian", "fullscreen": True}})
        self.assertEqual(window, "Huian")
        named.assert_called_once()
        self.assertEqual(named.call_args.args[0], "Huian")
        fullscreen.assert_called_once()

    def test_fullscreen_can_be_disabled_for_debugging(self):
        with patch("vision.camera_runner.cv2.namedWindow") as named, patch("vision.camera_runner.cv2.setWindowProperty") as fullscreen:
            _configure_live_window({"display_window": True, "display": {"fullscreen": False}})
        named.assert_called_once()
        fullscreen.assert_not_called()

    def test_live_and_offline_fire_budgets_remain_separate(self):
        live = json.loads((ROOT / "rpi_app/configs/rpi_imx219_live.json").read_text(encoding="utf-8"))
        offline = json.loads((ROOT / "rpi_app/configs/fire_demo_01.json").read_text(encoding="utf-8"))
        self.assertTrue(live["display"]["fullscreen"])
        self.assertEqual((live["fire_detection"]["tile_rows"], live["fire_detection"]["tile_cols"]), (2, 2))
        self.assertEqual(live["fire_detection"]["confidence"], 0.18)
        self.assertEqual((offline["fire_detection"]["tile_rows"], offline["fire_detection"]["tile_cols"]), (3, 3))
        self.assertTrue(offline["fire_detection"]["full_frame_pass"])
        self.assertEqual(offline["fire_detection"]["confidence"], 0.15)


if __name__ == "__main__":
    unittest.main()