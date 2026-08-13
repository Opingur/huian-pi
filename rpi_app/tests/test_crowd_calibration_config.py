import json
import unittest
from pathlib import Path


class CrowdCalibrationConfigTests(unittest.TestCase):
    def test_active_configs_start_uncalibrated_without_a_danger_fallback(self):
        app_root = Path(__file__).resolve().parents[1]
        paths = [app_root / "config.json", *sorted((app_root / "configs").glob("*.json"))]
        for path in paths:
            with self.subTest(path=path.name):
                config = json.loads(path.read_text(encoding="utf-8"))
                calibration = config["crowd_calibration"]
                self.assertFalse(calibration["calibrated"])
                self.assertIsNone(calibration["danger_people_threshold"])
                self.assertEqual(calibration["calibration_source"], "pending_real_stair_experiment")
