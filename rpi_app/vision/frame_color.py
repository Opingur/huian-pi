"""Colour-space boundary for Picamera2 camera frames.

Picamera2's RGB888 format name follows the libcamera pixel-format convention.
Its ``capture_array()`` three-channel ndarray is already laid out as [B, G, R],
which is the OpenCV representation. Internal OpenCV, YOLO, drawing, imshow,
and VideoWriter frames therefore remain BGR without a second channel swap.
"""

from __future__ import annotations

from typing import Any


PICAMERA2_RGB888_CAPTURE_ARRAY_COLOR_SPACE = "BGR"
INTERNAL_FRAME_COLOR_SPACE = "BGR"


def picamera_rgb888_capture_array_to_bgr(frame: Any):
    """Validate and pass through Picamera2 RGB888 capture_array output as OpenCV BGR."""
    if frame is None or getattr(frame, "ndim", None) != 3 or frame.shape[2] != 3:
        raise ValueError("Picamera2 RGB888 frame must be a three-channel image")
    return frame