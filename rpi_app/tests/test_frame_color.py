import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from vision import camera_runner
from vision.frame_color import (
    INTERNAL_FRAME_COLOR_SPACE,
    PICAMERA2_RGB888_CAPTURE_ARRAY_COLOR_SPACE,
    picamera_rgb888_capture_array_to_bgr,
)


class _FakePicamera2:
    captured_frame = None
    instances = []

    def __init__(self):
        self.configured = None
        self.started = False
        self.stopped = False
        self.closed = False
        self.__class__.instances.append(self)

    def create_video_configuration(self, main):
        return {"main": main}

    def configure(self, configuration):
        self.configured = configuration

    def start(self):
        self.started = True

    def capture_array(self):
        return self.__class__.captured_frame

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class _FakeProcessor:
    received_frames = []

    def __init__(self, *_args):
        self.publisher = SimpleNamespace(send_status=lambda *_args, **_kwargs: None)

    def process_live_frame(self, frame, _source_timestamp):
        self.__class__.received_frames.append(frame.copy())
        return frame, {}, False

    def close(self):
        pass


class FrameColorTests(unittest.TestCase):
    def setUp(self):
        _FakePicamera2.instances = []
        _FakeProcessor.received_frames = []

    def test_rgb888_capture_array_contract_is_already_opencv_bgr(self):
        # Picamera2 RGB888 capture_array uses the current documented OpenCV-facing [B, G, R] ndarray order.
        picamera_array = np.array([[[0, 0, 255], [0, 255, 0], [255, 0, 0]]], dtype=np.uint8)
        received = picamera_rgb888_capture_array_to_bgr(picamera_array)
        self.assertEqual(PICAMERA2_RGB888_CAPTURE_ARRAY_COLOR_SPACE, "BGR")
        self.assertEqual(INTERNAL_FRAME_COLOR_SPACE, "BGR")
        self.assertIs(received, picamera_array)
        self.assertEqual(received[0, 0].tolist(), [0, 0, 255])
        self.assertEqual(received[0, 2].tolist(), [255, 0, 0])

    def test_capture_array_to_live_processor_has_no_extra_red_blue_swap(self):
        # Exercise the real camera-runner boundary, rather than only a standalone converter.
        expected_bgr = np.array([[[0, 0, 255], [0, 255, 0], [255, 0, 0]]], dtype=np.uint8)
        _FakePicamera2.captured_frame = expected_bgr
        fake_picamera2_module = SimpleNamespace(Picamera2=_FakePicamera2)
        config = {
            "display_window": True,
            "camera": {"width": 3, "height": 1, "format": "RGB888"},
            "display": {"fullscreen": False, "window_name": "colour-test"},
            "live_processing": {"performance_log_enabled": False},
        }
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(sys.modules, {"picamera2": fake_picamera2_module}), \
             patch("vision.camera_runner.TrackedFrameProcessor", _FakeProcessor), \
             patch("vision.camera_runner.cv2.namedWindow"), \
             patch("vision.camera_runner.cv2.imshow"), \
             patch("vision.camera_runner.cv2.waitKey", return_value=ord("q")), \
             patch("vision.camera_runner.cv2.destroyAllWindows"):
            camera_runner.run_picamera2_camera(config, Path(directory), lambda *_args: {})

        self.assertEqual(len(_FakeProcessor.received_frames), 1)
        np.testing.assert_array_equal(_FakeProcessor.received_frames[0], expected_bgr)
        self.assertTrue(_FakePicamera2.instances[0].started)
        self.assertTrue(_FakePicamera2.instances[0].stopped)
        self.assertTrue(_FakePicamera2.instances[0].closed)

    def test_camera_runner_has_no_rgb_to_bgr_conversion(self):
        source = Path(camera_runner.__file__).read_text(encoding="utf-8")
        self.assertIn("frame_bgr = picamera_rgb888_capture_array_to_bgr(frame_rgb)", source)
        self.assertNotIn("cv2.COLOR_RGB2BGR", source)
        self.assertNotIn("cvtColor(frame_rgb", source)


if __name__ == "__main__":
    unittest.main()