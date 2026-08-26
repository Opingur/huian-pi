"""Frame-level adapter for Ground Truth; delegates YOLO work to existing teaching service."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

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

    def analyze_samples(self, samples: Iterable[tuple[str, int]]) -> list[tuple[str, int]]:
        """Run real person detection once for every pre-created research sample."""
        results: list[tuple[str, int]] = []
        for annotation_id, frame_index in samples:
            packet = self.detect(frame_index)
            results.append((annotation_id, len(packet.rows)))
        return results

    def close(self) -> None:
        self._vision.close()
