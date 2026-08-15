import unittest

from teaching_console.pages.research_page import (
    format_prediction_error,
    format_prediction_mae,
    format_prediction_slope,
    format_prediction_value,
)


class PredictionDisplayFormatTests(unittest.TestCase):
    def test_prediction_values_are_ui_rounded_only(self):
        self.assertEqual(format_prediction_slope(0.66666666), "+0.667")
        self.assertEqual(format_prediction_value(17.700000000000001), "17.7")
        self.assertEqual(format_prediction_error(2.0), "2.0")
        self.assertEqual(format_prediction_mae(0.9499999999999993), "0.95")
        self.assertEqual(format_prediction_mae(7.300000000000001), "7.30")

    def test_missing_values_are_explicit(self):
        for formatter in (
            format_prediction_slope,
            format_prediction_value,
            format_prediction_error,
            format_prediction_mae,
        ):
            self.assertEqual(formatter(None), "暂无数据")

