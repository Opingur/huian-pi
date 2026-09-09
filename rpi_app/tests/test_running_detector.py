import unittest

from vision.running_detector import SHOWCASE_RUNNING_DETECTION_PROFILE, RunningDetector, aggregate_running


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
        result = self.detector.update([track(1000, height=300)], 0.4)[7]
        self.assertFalse(result["running"])
        self.assertEqual(result["normalized_speed"], 0.0)

    def test_close_range_rapid_continuous_motion_triggers(self):
        detector = RunningDetector({
            "window_seconds": 0.7, "enter_threshold": 1.0, "exit_threshold": 0.55,
            "confirm_seconds": 0.2, "release_seconds": 0.5, "minimum_track_history": 0.35,
            "max_sample_speed": 5.0, "max_sample_gap_seconds": 0.85,
            "max_scale_change_ratio": 1.45, "pixel_enter_threshold": 180,
            "pixel_exit_threshold": 120,
        })
        for time, x in ((0.0, 0), (0.2, 90), (0.4, 180), (0.65, 292)):
            result = detector.update([track(x)], time)[7]
        self.assertTrue(result["running"])
        self.assertGreater(result["pixel_speed"], 180)

    def test_showcase_profile_detects_sustained_distant_running(self):
        """The scaled low-resolution showcase must still flag a stable runner."""
        detector = RunningDetector(SHOWCASE_RUNNING_DETECTION_PROFILE)
        for timestamp, x in ((0.0, 0), (0.2, 30), (0.4, 62), (0.6, 94), (0.8, 126)):
            result = detector.update([track(x, height=150)], timestamp)[7]
        self.assertTrue(result["running"])

    def test_showcase_profile_does_not_flag_stable_walking(self):
        """Smooth walking is below the running profile even after several samples."""
        detector = RunningDetector(SHOWCASE_RUNNING_DETECTION_PROFILE)
        for timestamp, x in ((0.0, 0), (0.2, 22), (0.4, 44), (0.6, 66), (0.8, 88), (1.0, 110)):
            result = detector.update([track(x, height=150)], timestamp)[7]
        self.assertFalse(result["running"])

    def test_showcase_profile_requires_repeated_high_speed_evidence(self):
        """One noisy high-speed displacement must not immediately make a runner."""
        detector = RunningDetector(SHOWCASE_RUNNING_DETECTION_PROFILE)
        detector.update([track(0, height=150)], 0.0)
        result = detector.update([track(36, height=150)], 0.2)[7]
        self.assertFalse(result["running"])
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
