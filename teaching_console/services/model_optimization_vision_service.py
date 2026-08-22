"""Real video inspection adapter for the model-optimization teaching page.

It deliberately delegates person inference to ``VisionTeachingService`` which,
in turn, uses the repository's ``PersonDetector``.  It never trains a model.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teaching_console.services.vision_teaching_service import MODE_DETECT, MODE_RAW, VisionTeachingService


@dataclass(frozen=True)
class DifficultFrame:
    frame_index: int
    time_seconds: float
    system_count: int
    average_confidence: float | None
    minimum_confidence: float | None
    reasons: tuple[str, ...]
    score: float


def select_difficult_frames(
    candidates: list[DifficultFrame], maximum: int, minimum_frame_gap: int,
) -> tuple[DifficultFrame, ...]:
    """Rank candidates while keeping neighbouring near-duplicate frames apart."""
    maximum = max(5, min(25, int(maximum)))
    chosen: list[DifficultFrame] = []
    for candidate in sorted(candidates, key=lambda item: (-item.score, item.frame_index)):
        if all(abs(candidate.frame_index - prior.frame_index) >= minimum_frame_gap for prior in chosen):
            chosen.append(candidate)
        if len(chosen) >= maximum:
            break
    return tuple(sorted(chosen, key=lambda item: item.frame_index))


class ModelOptimizationVisionService:
    """Own a video capture and lazily use the real person detector for inspection."""

    def __init__(self, project_root: Path) -> None:
        self._vision = VisionTeachingService(project_root)
        self.video = None

    def open_video(self, path: Path):
        self.video = self._vision.open_video(path)
        return self.video

    def read_raw(self, frame_index: int):
        return self._vision.read_frame(frame_index, MODE_RAW)

    def detect(self, frame_index: int):
        return self._vision.read_frame(frame_index, MODE_DETECT)

    def analyze_difficult_frames(self, maximum: int = 25) -> tuple[DifficultFrame, ...]:
        if self.video is None:
            raise RuntimeError("请先选择一个视频。")
        maximum = max(5, min(25, int(maximum)))
        # A bounded, evenly distributed inspection avoids treating every video
        # frame as an annotation task while retaining enough context for jumps.
        sample_count = min(self.video.total_frames, max(20, maximum * 5))
        indices = sorted({round(index * (self.video.total_frames - 1) / max(1, sample_count - 1)) for index in range(sample_count)})
        candidates: list[DifficultFrame] = []
        prior_count: int | None = None
        for frame_index in indices:
            packet = self.detect(frame_index)
            confidences = [row.confidence for row in packet.rows]
            count = len(packet.rows)
            average = sum(confidences) / len(confidences) if confidences else None
            minimum = min(confidences) if confidences else None
            reasons: list[str] = []
            score = float(count) * 2.0
            if count >= 5:
                reasons.append("当前人数较多")
                score += count
            low_confidence = sum(value < 0.55 for value in confidences)
            if low_confidence:
                reasons.append(f"低置信度 person {low_confidence} 个")
                score += low_confidence * 2.0
            if prior_count is not None and abs(count - prior_count) >= 2:
                reasons.append("连续采样人数明显跳变")
                score += abs(count - prior_count) * 2.0
            if count >= 2 and not reasons:
                reasons.append("多人同框，建议检查遮挡")
                score += 0.5
            if not reasons:
                reasons.append("均匀抽样补充场景")
            candidates.append(DifficultFrame(
                frame_index, packet.seconds, count, average, minimum, tuple(reasons), score,
            ))
            prior_count = count
        minimum_gap = max(1, self.video.total_frames // max(1, maximum * 2))
        return select_difficult_frames(candidates, maximum, minimum_gap)

    def close(self) -> None:
        self._vision.close()
