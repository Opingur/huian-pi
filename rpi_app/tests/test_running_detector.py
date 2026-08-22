import unittest

from vision.running_detector import RunningDetector, aggregate_running


def track(x, *, track_id=7, height=100):
    return {"track_id": track_id, "x1": x, "y1": 100, "x2": x + 50, "y2": 100 + height}


class RunningDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = RunningDetector({
            "window_seconds": 0.8, "enter_threshold": 1.0, "exit_threshold": 0.5,
            "confirm_seconds": 0.2, "release_seconds": 0.2, "minimum_track_history": 0.3,
            "max_sample_speed": 4.0,
        })

    def update(self, time, x, track_id=7):
        return self.detector.update([track(x, track_id=track_id)], time)[track_id]

    def test_history_low_speed_and_high_speed_confirmation(self):
        self.assertFalse(self.update(0.0, 0)["running"])
        self.assertFalse(self.update(0.2, 5)["running"])
        self.assertFalse(self.update(0.4, 10)["running"])
        self.assertFalse(self.update(1.0, 100)["running"])
        self.assertFalse(self.update(1.2, 125)["running"])
        self.assertTrue(self.update(1.5, 160)["running"])
        self.assertGreater(self.update(1.6, 172)["running_duration"], 0.0)

    def test_one_frame_jump_is_not_running(self):
        self.update(0.0, 0)
        result = self.update(0.4, 1000)
        self.assertFalse(result["running"])
        self.assertEqual(result["normalized_speed"], 0.0)

    def test_exit_hysteresis_and_multiple_ids(self):
        for time, x in ((0.0, 0), (0.3, 40), (0.6, 80), (0.9, 120)):
            self.update(time, x)
        self.assertTrue(self.update(1.2, 160)["running"])
        self.assertTrue(self.update(1.5, 165)["running"])
        self.assertTrue(self.update(1.8, 165)["running"])
        self.assertFalse(self.update(2.1, 165)["running"])
        result = self.detector.update([track(0, track_id=1), track(0, track_id=2)], 2.0)
        self.assertEqual(sorted(result), [1, 2])
        self.assertFalse(any(item["running"] for item in result.values()))

    def test_running_count_and_track_ids_are_aggregated(self):
        summary = aggregate_running({4: {"running": True}, 1: {"running": False}, 8: {"running": True}})
        self.assertEqual(summary["running_track_ids"], [4, 8])
        self.assertEqual(summary["running_count"], 2)
        self.assertTrue(summary["running_event"])

if __name__ == "__main__":
    unittest.main()
