"""Frame-level adapter for Ground Truth; delegates all YOLO work to existing teaching service."""
from __future__ import annotations

from pathlib import Path

from teaching_console.services.vision_teaching_service import MODE_DETECT, MODE_RAW, VisionTeachingService


class ResearchVisionService:
    def __init__(self, project_root: Path) -> None:
        self._vision = VisionTeachingService(project_root)

    def open_video(self, path: Path):
        return self._vision.open_video(path)

    def read_raw(self, frame_index: int):
        return self._vision.read_frame(frame_index, MODE_RAW)

    def detect(self, frame_index: int):
        """Lazily invokes the real PersonDetector.detect() through the existing adapter."""
        return self._vision.read_frame(frame_index, MODE_DETECT)

    def close(self) -> None:
        self._vision.close()
