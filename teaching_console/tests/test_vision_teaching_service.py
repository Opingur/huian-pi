from __future__ import annotations

import unittest

from teaching_console.project_paths import project_root
from teaching_console.services.vision_teaching_service import (
    MODE_DETECT,
    MODE_RAW,
    MODE_TRACK,
    VisionTeachingService,
    find_example_video,
    load_vision_config,
    rows_from_results,
    teaching_cases,
)


class FakeFrame:
    def copy(self):
        return FakeFrame()


class FakeCapture:
    def __init__(self) -> None:
        self.position = 0
        self.released = False

    def isOpened(self) -> bool:
        return True

    def release(self) -> None:
        self.released = True

    def get(self, property_id):
        return {1: 15.0, 2: 5, 3: 1280, 4: 720}.get(property_id, 0)

    def set(self, property_id, value) -> None:
        if property_id == 5:
            self.position = int(value)

    def read(self):
        return True, FakeFrame()


class FakeCV2:
    CAP_PROP_FPS = 1
    CAP_PROP_FRAME_COUNT = 2
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_POS_FRAMES = 5
    FONT_HERSHEY_SIMPLEX = 6

    def __init__(self) -> None:
        self.captures = []

    def VideoCapture(self, _path):
        capture = FakeCapture()
        self.captures.append(capture)
        return capture

    @staticmethod
    def rectangle(*_args):
        pass

    @staticmethod
    def putText(*_args):
        pass

    @staticmethod
    def circle(*_args):
        pass


class FakeDetector:
    def detect(self, _frame):
        return [{"class": "person", "confidence": 0.8, "x1": 1, "y1": 2, "x2": 30, "y2": 40}]


class FakeTracker:
    def track(self, _frame):
        return [{"class": "person", "confidence": 0.9, "x1": 1, "y1": 2, "x2": 30, "y2": 40,
                 "track_id": 7, "anchor_x": 15, "anchor_y": 40}]


class VisionTeachingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = project_root()
        self.cv2 = FakeCV2()
        self.detector_builds = 0
        self.tracker_builds = 0

        def detector_factory(*_args):
            self.detector_builds += 1
            return FakeDetector()

        def tracker_factory(*_args):
            self.tracker_builds += 1
            return FakeTracker()

        self.service = VisionTeachingService(
            self.root, cv2_loader=lambda: self.cv2,
            detector_factory=detector_factory, tracker_factory=tracker_factory,
        )
        self.service.open_video(find_example_video(self.root))

    def tearDown(self) -> None:
        self.service.close()

    def test_config_and_example_video_are_project_relative(self) -> None:
        config = load_vision_config(self.root)
        video = find_example_video(self.root)
        self.assertEqual(config.model_path.name, "yolov8n.pt")
        self.assertEqual(config.confidence, 0.35)
        self.assertEqual(config.tracker, "bytetrack.yaml")
        self.assertEqual(video.relative_to(self.root).as_posix(), "test_data/000327.mp4")
        cases = teaching_cases(self.root)
        self.assertEqual([code for code, _purpose, _path in cases], ["000318", "000327", "000345", "000353"])
        self.assertTrue(all("final_dashboard_videos" not in str(path) for _code, _purpose, path in cases))

    def test_detection_and_tracking_rows_have_different_fields(self) -> None:
        detected = rows_from_results(FakeDetector().detect(None), tracking=False)[0]
        tracked = rows_from_results(FakeTracker().track(None), tracking=True)[0]
        self.assertEqual(detected.track_id, None)
        self.assertEqual(detected.anchor, None)
        self.assertEqual(tracked.track_id, 7)
        self.assertEqual(tracked.anchor, (15, 40))

    def test_raw_mode_does_not_create_detector_or_tracker(self) -> None:
        packet = self.service.read_frame(0, MODE_RAW)
        self.assertEqual(packet.rows, ())
        self.assertEqual(self.detector_builds, 0)
        self.assertEqual(self.tracker_builds, 0)

    def test_detection_is_lazy_and_does_not_use_tracker(self) -> None:
        packet = self.service.read_frame(0, MODE_DETECT)
        self.assertEqual(len(packet.rows), 1)
        self.assertEqual(self.detector_builds, 1)
        self.assertEqual(self.tracker_builds, 0)

    def test_tracker_resets_when_video_is_not_continuous(self) -> None:
        first = self.service.read_frame(0, MODE_TRACK, sequential=False)
        second = self.service.read_frame(1, MODE_TRACK, sequential=True)
        sought_back = self.service.read_frame(0, MODE_TRACK, sequential=False)
        self.assertTrue(first.tracker_reset)
        self.assertFalse(second.tracker_reset)
        self.assertTrue(sought_back.tracker_reset)
        self.assertEqual(self.tracker_builds, 2)


if __name__ == "__main__":
    unittest.main()
