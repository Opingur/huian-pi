import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from ui import startup_screen
from vision import camera_runner


class StartupScreenTests(unittest.TestCase):
    def test_initializing_frame_is_fullscreen_sized_and_has_required_text(self):
        with patch("ui.startup_screen._draw_text", side_effect=lambda image, *_args: image) as draw_text:
            image = startup_screen.draw_startup_frame()
        self.assertEqual(image.shape, (1024, 1280, 3))
        entries = draw_text.call_args.args[1]
        self.assertIn(((390, 430), "慧安安全监测系统", (40, 200, 255), 34), entries)
        self.assertIn(((500, 500), "系统初始化中…", (190, 205, 225), 23), entries)

    def test_error_frame_uses_a_concise_real_startup_failure_message(self):
        self.assertEqual(startup_screen.startup_failure_message(RuntimeError("Picamera2 unavailable")), "摄像头初始化失败")
        self.assertEqual(startup_screen.startup_failure_message(FileNotFoundError("Fire model not found")), "视觉模型加载失败")
        with patch("ui.startup_screen._draw_text", side_effect=lambda image, *_args: image):
            image = startup_screen.draw_startup_frame("摄像头初始化失败", error=True)
        self.assertEqual(image.shape, (1024, 1280, 3))

    def test_headless_startup_screen_never_calls_opencv_gui(self):
        screen = startup_screen.StartupScreen(None, {})
        with patch("ui.startup_screen.cv2.imshow") as imshow, patch("ui.startup_screen.cv2.waitKey") as wait_key:
            screen.show()
            screen.wait_for_exit()
        imshow.assert_not_called()
        wait_key.assert_not_called()

    def test_no_display_camera_path_never_creates_startup_or_opencv_window(self):
        class FakePicamera2:
            def create_video_configuration(self, main):
                return {"main": main}

            def configure(self, _configuration):
                pass

            def start(self):
                pass

            def capture_array(self):
                return np.zeros((1, 1, 3), dtype=np.uint8)

            def stop(self):
                pass

            def close(self):
                pass

        class InterruptingProcessor:
            def __init__(self, *_args):
                self.publisher = SimpleNamespace(send_status=lambda *_args, **_kwargs: None)

            def process_live_frame(self, *_args):
                raise KeyboardInterrupt

            def close(self):
                pass

        config = {
            "display_window": False,
            "camera": {"width": 1, "height": 1, "format": "RGB888"},
            "display": {},
            "live_processing": {"performance_log_enabled": False},
        }
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(sys.modules, {"picamera2": SimpleNamespace(Picamera2=FakePicamera2)}), \
             patch("vision.camera_runner.TrackedFrameProcessor", InterruptingProcessor), \
             patch("vision.camera_runner.cv2.namedWindow") as named_window, \
             patch("vision.camera_runner.cv2.imshow") as imshow:
            with self.assertRaises(KeyboardInterrupt):
                camera_runner.run_picamera2_camera(config, Path(directory), lambda *_args: {})
        named_window.assert_not_called()
        imshow.assert_not_called()

    def test_camera_runner_shows_splash_before_camera_and_processor_initialization(self):
        source = inspect.getsource(camera_runner.run_picamera2_camera)
        self.assertLess(source.index("startup.show(STARTUP_INITIALIZING)"), source.index("from picamera2 import Picamera2"))
        self.assertLess(source.index("startup.show(STARTUP_INITIALIZING)"), source.index("TrackedFrameProcessor(config, build_status)"))


if __name__ == "__main__":
    unittest.main()