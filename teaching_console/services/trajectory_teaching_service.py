"""Teaching adapter that composes the formal ByteTrack and trajectory pipeline."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from teaching_console.services.vision_teaching_service import (
    MODE_RAW,
    MODE_TRACK,
    FramePacket,
    TeachingRow,
    VisionTeachingError,
    VisionTeachingService,
)


LAYER_RAW = "raw"
LAYER_TRACK = "track"
LAYER_TRAIL = "trail"
LAYER_DIRECTION = "direction"


@dataclass(frozen=True)
class TrajectoryFramePacket:
    """One video frame plus unmodified formal TrajectoryAnalyzer output."""

    frame: FramePacket
    motions: dict[int, dict[str, object]]
    trajectory_reset: bool


def load_trajectory_config(root: Path) -> tuple[dict[str, object], list[list[float]]]:
    """Read the formal trajectory settings without changing their defaults."""
    config_path = Path(root) / "rpi_app" / "config.json"
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VisionTeachingError(f"无法读取项目轨迹配置：{error}") from error
    tracking = data.get("tracking", {})
    if not isinstance(tracking, dict):
        tracking = {}
    conflict_zone = data.get("conflict_zone", [])
    return dict(tracking), list(conflict_zone) if isinstance(conflict_zone, list) else []


def active_track_ids(rows: tuple[TeachingRow, ...]) -> tuple[int, ...]:
    """Return current active IDs for the page selector; empty frames return no stale IDs."""
    return tuple(sorted({int(row.track_id) for row in rows if row.track_id is not None}))


def motion_display_data(motion: dict[str, object], frame_width: int, frame_height: int) -> dict[str, object]:
    """Convert formal normalized trail points to pixels for explanation only."""
    width, height = max(int(frame_width), 1), max(int(frame_height), 1)
    trail = tuple(
        (float(timestamp), int(round(float(x) * width)), int(round(float(y) * height)))
        for timestamp, x, y in motion.get("trail", [])
    )
    anchor_x, anchor_y = motion.get("anchor_point", (0.0, 0.0))
    anchor = (int(round(float(anchor_x) * width)), int(round(float(anchor_y) * height)))
    start = (trail[0][1], trail[0][2]) if trail else anchor
    end = (trail[-1][1], trail[-1][2]) if trail else anchor
    return {
        "track_id": int(motion["track_id"]),
        "anchor": anchor,
        "trail": trail,
        "start": start,
        "end": end,
        "dx_pixels": end[0] - start[0],
        "dy_pixels": end[1] - start[1],
        "dx_norm": motion.get("dx", 0.0),
        "dy_norm": motion.get("dy", 0.0),
        "speed_norm": motion.get("speed_norm", 0.0),
        "heading_angle": motion.get("heading_angle"),
        "motion_state": motion.get("motion_state", "UNCERTAIN"),
    }


class TrajectoryTeachingService(VisionTeachingService):
    """Reuse the formal PersonTracker and TrajectoryAnalyzer in one serial worker."""

    def __init__(
        self,
        root: Path,
        *,
        cv2_loader: Callable[[], Any] | None = None,
        tracker_factory: Callable[[Path, float, str, int], Any] | None = None,
        trajectory_factory: Callable[[dict[str, object]], Any] | None = None,
    ) -> None:
        self.trajectory_config, self.conflict_zone = load_trajectory_config(root)
        self._trajectory_factory = trajectory_factory or self._build_trajectory_analyzer
        self._trajectory: Any | None = None
        super().__init__(root, cv2_loader=cv2_loader, tracker_factory=tracker_factory)

    @staticmethod
    def _build_trajectory_analyzer(config: dict[str, object]) -> Any:
        try:
            from rpi_app.vision.trajectory import TrajectoryAnalyzer
        except ImportError as error:
            raise VisionTeachingError("无法导入项目 TrajectoryAnalyzer。") from error
        return TrajectoryAnalyzer(config)

    def _ensure_trajectory(self) -> Any:
        if self._trajectory is None:
            self._trajectory = self._trajectory_factory(self.trajectory_config)
        return self._trajectory

    def reset_trajectory(self) -> None:
        self._trajectory = None

    def reset_tracker(self) -> None:
        super().reset_tracker()
        self.reset_trajectory()

    def read_trajectory_frame(
        self,
        frame_index: int,
        layer: str,
        sequential: bool = False,
    ) -> TrajectoryFramePacket:
        if layer == LAYER_RAW:
            self.reset_tracker()
            return TrajectoryFramePacket(super().read_frame(frame_index, MODE_RAW), {}, True)
        if layer not in {LAYER_TRACK, LAYER_TRAIL, LAYER_DIRECTION}:
            raise VisionTeachingError(f"未知轨迹观察层级：{layer}")

        frame = super().read_frame(frame_index, MODE_TRACK, sequential)
        if layer == LAYER_TRACK:
            return TrajectoryFramePacket(frame, {}, frame.tracker_reset)
        formal_tracks = [
            {
                "track_id": int(row.track_id),
                "anchor_x": int(row.anchor[0]),
                "anchor_y": int(row.anchor[1]),
            }
            for row in frame.rows
            if row.track_id is not None and row.anchor is not None
        ]
        motions = self._ensure_trajectory().update(
            formal_tracks,
            frame.video.width,
            frame.video.height,
            frame.seconds,
            self.conflict_zone,
        )
        return TrajectoryFramePacket(frame, motions, frame.tracker_reset)

