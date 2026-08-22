"""OpenCV MP4 source adapter used by the Windows formal demo entry point."""

from __future__ import annotations

from pathlib import Path

import cv2


class VideoSource:
    """Yield decoded BGR frames with timestamps from the video timeline."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.capture = cv2.VideoCapture(str(self.path))
        if not self.capture.isOpened():
            raise RuntimeError(f"Unable to open video: {self.path}")
        self.fps = float(self.capture.get(cv2.CAP_PROP_FPS)) or 25.0
        self.frame_count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self.width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.frame_index = 0

    def read(self):
        success, frame = self.capture.read()
        if not success:
            return None
        position_ms = float(self.capture.get(cv2.CAP_PROP_POS_MSEC))
        source_time = position_ms / 1000.0 if position_ms > 0 else self.frame_index / self.fps
        self.frame_index += 1
        return frame, source_time

    def close(self) -> None:
        self.capture.release()
