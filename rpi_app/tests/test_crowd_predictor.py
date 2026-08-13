import unittest

from decision.crowd_predictor import CrowdPredictor


class CrowdPredictorCalibrationTests(unittest.TestCase):
    config = {
        "enabled": True,
        "window_seconds": 15,
        "min_samples": 5,
        "min_history_seconds": 8,
        "horizons": [10, 20, 30],
        "max_eta_seconds": 120,
    }
    rising_history = [(0.0, 0, 0), (2.0, 2, 0), (4.0, 4, 0), (6.0, 6, 0), (8.0, 8, 0)]

    def test_uncalibrated_keeps_forecast_but_has_no_danger_eta(self):
        forecast = CrowdPredictor(self.config, {
            "calibrated": False,
            "danger_people_threshold": None,
        }).predict(self.rising_history, current_people=8)
        self.assertTrue(forecast["prediction_valid"])
        self.assertEqual(forecast["prediction_slope"], 1.0)
        self.assertEqual(forecast["predicted_people"], {10: 18.0, 20: 28.0, 30: 38.0})
        self.assertIsNone(forecast["time_to_danger"])
        self.assertFalse(forecast["crowd_calibrated"])
        self.assertIsNone(forecast["danger_people_threshold"])

    def test_calibrated_threshold_18_drives_danger_eta(self):
        forecast = CrowdPredictor(self.config, {
            "calibrated": True,
            "danger_people_threshold": 18,
        }).predict(self.rising_history, current_people=8)
        self.assertTrue(forecast["crowd_calibrated"])
        self.assertEqual(forecast["danger_people_threshold"], 18)
        self.assertEqual(forecast["time_to_danger"], 10.0)
        self.assertEqual(forecast["predicted_risk"][10], "DANGER")

    def test_calibrated_threshold_20_replaces_18_without_fallback(self):
        forecast = CrowdPredictor(self.config, {
            "calibrated": True,
            "danger_people_threshold": 20,
        }).predict(self.rising_history, current_people=8)
        self.assertEqual(forecast["danger_people_threshold"], 20)
        self.assertEqual(forecast["time_to_danger"], 12.0)
        self.assertEqual(forecast["predicted_risk"][10], "WARNING")
        self.assertEqual(forecast["predicted_risk"][20], "DANGER")

    def test_non_positive_slope_has_no_danger_eta(self):
        falling_history = [(0.0, 10, 0), (2.0, 8, 0), (4.0, 6, 0), (6.0, 4, 0), (8.0, 2, 0)]
        forecast = CrowdPredictor(self.config, {
            "calibrated": True,
            "danger_people_threshold": 20,
        }).predict(falling_history, current_people=2)
        self.assertTrue(forecast["prediction_valid"])
        self.assertLessEqual(forecast["prediction_slope"], 0)
        self.assertIsNone(forecast["time_to_danger"])


if __name__ == "__main__":
    unittest.main()
