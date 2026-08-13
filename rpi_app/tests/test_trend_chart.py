import unittest
from unittest.mock import patch

import numpy as np

from ui.trend_chart import draw_trend_chart


class TrendChartCalibrationTests(unittest.TestCase):
    history = [(0.0, 4, 0), (8.0, 8, 0)]
    forecast = {
        "prediction_valid": True,
        "prediction_slope": 1.0,
        "predicted_people_10s": 18.0,
        "predicted_people_20s": 28.0,
        "predicted_people_30s": 38.0,
    }

    def test_uncalibrated_chart_does_not_draw_danger_reference(self):
        image = np.zeros((200, 400, 3), dtype=np.uint8)
        status = {**self.forecast, "crowd_calibrated": False}
        with patch("ui.trend_chart.cv2.line") as line:
            self.assertTrue(draw_trend_chart(image, (0, 0, 400, 200), self.history, status, danger_people=None))
        self.assertNotIn((80, 80, 220), [call.args[3] for call in line.call_args_list if len(call.args) > 3])

    def test_calibrated_chart_draws_the_given_reference_only(self):
        image = np.zeros((200, 400, 3), dtype=np.uint8)
        status = {**self.forecast, "crowd_calibrated": True}
        with patch("ui.trend_chart.cv2.line") as line:
            self.assertTrue(draw_trend_chart(image, (0, 0, 400, 200), self.history, status, danger_people=20))
        self.assertIn((80, 80, 220), [call.args[3] for call in line.call_args_list if len(call.args) > 3])


if __name__ == "__main__":
    unittest.main()
