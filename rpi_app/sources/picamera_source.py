"""Lazy Picamera2 input adapter for the Raspberry Pi IMX219 runtime."""

from __future__ import annotations

import time
from typing import Any

try:
    from rpi_app.vision.frame_color import picamera_rgb888_capture_array_to_bgr
except ModuleNotFoundError:  # Script-style Pi execution keeps rpi_app as the import root.
    from vision.frame_color import picamera_rgb888_capture_array_to_bgr


class PicameraSource:
    """Provide BGR frames and monotonic source-time without importing Picamera2 on Windows."""

    def __init__(self, camera_config: dict[str, Any] | None = None) -> None:
        settings = dict(camera_config or {})
        self.width = int(settings.get("width", 1280))
        self.height = int(settings.get("height", 720))
        self.pixel_format = str(settings.get("format", "RGB888"))
        if self.pixel_format != "RGB888":
            raise ValueError("camera.format currently supports RGB888 only")
        self._camera: Any | None = None
        self._started = False
        self._started_at: float | None = None

    def start(self) -> None:
        """Open and configure CSI hardware only for the Pi camera runtime."""
        if self._camera is not None:
            return
        try:
            from picamera2 import Picamera2
        except ImportError as error:
            raise RuntimeError(
                "source_type=camera requires Picamera2 on Raspberry Pi; image/video modes do not need it."
            ) from error
        camera = Picamera2()
        try:
            camera.configure(
                camera.create_video_configuration(
                    main={"size": (self.width, self.height), "format": self.pixel_format}
                )
            )
            camera.start()
        except Exception:
            try:
                camera.close()
            finally:
                raise
        self._camera = camera
        self._started = True
        self._started_at = time.monotonic()

    def read(self):
        """Return one ``(BGR frame, source_time)`` sample from the camera timeline."""
        if self._camera is None or self._started_at is None:
            raise RuntimeError("PicameraSource.start() must be called before read().")
        frame_rgb = self._camera.capture_array()
        if frame_rgb is None or frame_rgb.ndim != 3 or frame_rgb.shape[2] != 3:
            raise RuntimeError("Picamera2 RGB888 capture did not return a three-channel frame")
        frame_bgr = picamera_rgb888_capture_array_to_bgr(frame_rgb)
        return frame_bgr, time.monotonic() - self._started_at

    def close(self) -> None:
        """Release the Pi camera safely; this is a no-op if opening failed."""
        camera, self._camera = self._camera, None
        started, self._started = self._started, False
        self._started_at = None
        if camera is not None:
            try:
                if started:
                    camera.stop()
            finally:
                camera.close()