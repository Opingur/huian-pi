from __future__ import annotations

import unittest

from teaching_console.pages.research_page import prediction_target


class PredictionFrameTargetTests(unittest.TestCase):
    def test_targets_use_anchor_time_and_video_fps(self) -> None:
        self.assertEqual(prediction_target(8.0, 10, 15), (18.0, 270))
        self.assertEqual(prediction_target(8.0, 20, 15), (28.0, 420))
        self.assertEqual(prediction_target(8.0, 30, 15), (38.0, 570))


if __name__ == "__main__":
    unittest.main()
