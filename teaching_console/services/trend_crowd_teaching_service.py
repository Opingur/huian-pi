"""Teaching adapter for the formal people-flow, forecast and Crowd Index pipeline."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Callable

from teaching_console.services.vision_teaching_service import (
    MODE_TRACK,
    FramePacket,
    VisionTeachingError,
    VisionTeachingService,
)


@dataclass(frozen=True)
class TrendCrowdConfig:
    flow: dict[str, object]
    prediction: dict[str, object]
    tracking: dict[str, object]
    crowd_index: dict[str, object]
    flow_risk: dict[str, object]
    crowd_calibration: dict[str, object]
    conflict_zone: list[list[float]]
    warning_people: int
    danger_people: int


@dataclass(frozen=True)
class TrendCrowdPacket:
    """A tracked frame and values returned by the formal crowd-processing functions."""

    frame: FramePacket
    trend: Any
    forecast: dict[str, object]
    crowd_metrics: dict[str, object]
    flow_metrics: dict[str, object]
    base_risk: str
    risk_state: str
    history: tuple[tuple[float, int, int], ...]
    reset: bool


def load_trend_crowd_config(root: Path) -> TrendCrowdConfig:
    """Read the deployed formal settings; no teaching defaults are invented here."""
    path = Path(root) / "rpi_app" / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VisionTeachingError(f"无法读取项目趋势配置：{error}") from error
    return TrendCrowdConfig(
        flow={
            "window_seconds": data.get("flow_window_seconds", 30),
            "sample_interval_seconds": data.get("snapshot_interval_seconds", 1),
            "conflict_people_per_region": data.get("conflict_people_per_region", 4),
            "conflict_min_total": data.get("conflict_min_total", 10),
        },
        prediction=dict(data.get("prediction", {})),
        tracking=dict(data.get("tracking", {})),
        crowd_index=dict(data.get("crowd_index", {})),
        flow_risk=dict(data.get("flow_risk", {})),
        crowd_calibration=dict(data.get("crowd_calibration", {})),
        conflict_zone=list(data.get("conflict_zone", [])),
        warning_people=int(data.get("warning_people", 8)),
        danger_people=int(data.get("danger_people", 16)),
    )


class TrendCrowdTeachingService(VisionTeachingService):
    """One worker-owned pipeline composed only from existing formal project components."""

    def __init__(
        self,
        root: Path,
        *,
        cv2_loader: Callable[[], Any] | None = None,
        tracker_factory: Callable[[Path, float, str, int], Any] | None = None,
        flow_factory: Callable[[TrendCrowdConfig], Any] | None = None,
        predictor_factory: Callable[[TrendCrowdConfig], Any] | None = None,
        trajectory_factory: Callable[[TrendCrowdConfig], Any] | None = None,
        flow_risk_factory: Callable[[TrendCrowdConfig], Any] | None = None,
        crowd_index_calculator: Callable[..., dict[str, object]] | None = None,
        risk_engine_factory: Callable[[TrendCrowdConfig], Any] | None = None,
        risk_mapper: Callable[[str, dict[str, object]], str] | None = None,
        group_builder: Callable[[dict[int, dict[str, object]]], dict[int, dict[str, object]]] | None = None,
    ) -> None:
        self.trend_config = load_trend_crowd_config(root)
        self._flow_factory = flow_factory or self._build_people_flow
        self._predictor_factory = predictor_factory or self._build_predictor
        self._trajectory_factory = trajectory_factory or self._build_trajectory
        self._flow_risk_factory = flow_risk_factory or self._build_flow_risk
        self._crowd_index_calculator = crowd_index_calculator
        self._risk_engine_factory = risk_engine_factory or self._build_risk_engine
        self._risk_mapper = risk_mapper
        self._group_builder = group_builder or self._build_group_builder
        self._flow: Any | None = None
        self._predictor: Any | None = None
        self._trajectory: Any | None = None
        self._flow_risk: Any | None = None
        self._risk_engine: Any | None = None
        super().__init__(root, cv2_loader=cv2_loader, tracker_factory=tracker_factory)

    @staticmethod
    def _build_people_flow(config: TrendCrowdConfig) -> Any:
        from rpi_app.vision.people_flow import PeopleFlowAnalyzer
        return PeopleFlowAnalyzer(**config.flow)

    @staticmethod
    def _build_predictor(config: TrendCrowdConfig) -> Any:
        from rpi_app.decision.crowd_predictor import CrowdPredictor
        return CrowdPredictor(config.prediction, config.crowd_calibration)

    @staticmethod
    def _build_trajectory(config: TrendCrowdConfig) -> Any:
        from rpi_app.vision.trajectory import TrajectoryAnalyzer
        return TrajectoryAnalyzer(config.tracking)

    @staticmethod
    def _build_flow_risk(config: TrendCrowdConfig) -> Any:
        from rpi_app.decision.flow_analysis import FlowRiskAnalyzer
        return FlowRiskAnalyzer(config.flow_risk)

    @staticmethod
    def _build_crowd_index_calculator() -> Callable[..., dict[str, object]]:
        from rpi_app.decision.crowd_index import calculate_crowd_index
        return calculate_crowd_index

    @staticmethod
    def _build_risk_engine(config: TrendCrowdConfig) -> Any:
        from rpi_app.decision.risk_engine import RiskEngine
        return RiskEngine(config.warning_people, config.danger_people)

    @staticmethod
    def _build_group_builder(motions: dict[int, dict[str, object]]) -> dict[int, dict[str, object]]:
        from rpi_app.ui.flow_group_visualizer import build_flow_groups
        return build_flow_groups(motions)

    @staticmethod
    def _build_risk_mapper(root: Path) -> Callable[[str, dict[str, object]], str]:
        """Import the exact main-pipeline mapping without instantiating any hardware object."""
        rpi_root = str(Path(root) / "rpi_app")
        if rpi_root not in sys.path:
            sys.path.insert(0, rpi_root)
        from vision.video_runner import _apply_flow_risk
        return _apply_flow_risk

    def _ensure_analysis(self) -> tuple[Any, Any, Any, Any, Any]:
        if self._flow is None:
            self._flow = self._flow_factory(self.trend_config)
            self._predictor = self._predictor_factory(self.trend_config)
            self._trajectory = self._trajectory_factory(self.trend_config)
            self._flow_risk = self._flow_risk_factory(self.trend_config)
            self._risk_engine = self._risk_engine_factory(self.trend_config)
        if self._crowd_index_calculator is None:
            self._crowd_index_calculator = self._build_crowd_index_calculator()
        if self._risk_mapper is None:
            self._risk_mapper = self._build_risk_mapper(self.root)
        return self._flow, self._predictor, self._trajectory, self._flow_risk, self._risk_engine

    def reset_analysis(self) -> None:
        self._flow = self._predictor = self._trajectory = self._flow_risk = self._risk_engine = None

    def reset_tracker(self) -> None:
        super().reset_tracker()
        self.reset_analysis()

    def read_trend_frame(self, frame_index: int, sequential: bool = False) -> TrendCrowdPacket:
        """Run the same ordered analysis calls as the offline formal video path."""
        frame = super().read_frame(frame_index, MODE_TRACK, sequential)
        flow, predictor, trajectory, flow_risk, risk_engine = self._ensure_analysis()
        tracks = [
            {
                "track_id": int(row.track_id), "x1": row.bbox[0], "y1": row.bbox[1],
                "x2": row.bbox[2], "y2": row.bbox[3],
                "anchor_x": int(row.anchor[0]), "anchor_y": int(row.anchor[1]),
            }
            for row in frame.rows if row.track_id is not None and row.anchor is not None
        ]
        width, height = frame.video.width, frame.video.height
        left_people = sum(1 for track in tracks if (int(track["x1"]) + int(track["x2"])) // 2 < width // 2)
        right_people = len(tracks) - left_people
        trend, _snapshot_saved = flow.update(left_people, right_people, now=frame.seconds)
        forecast = predictor.predict(flow.history, trend.total_people)
        motions = trajectory.update(tracks, width, height, frame.seconds, self.trend_config.conflict_zone)
        flow_groups = self._group_builder(motions)
        flow_metrics = flow_risk.analyze(list(motions.values()), forecast, flow_groups)
        crowd_metrics = self._crowd_index_calculator(
            left_people, right_people, trend.occupancy_growth, trend.direction_conflict,
            self.trend_config.crowd_index, flow_metrics["convergence_score"],
        )
        base_risk = risk_engine.evaluate(
            left_people, right_people, trend.occupancy_growth, trend.direction_conflict, crowd_metrics["index"],
        )
        return TrendCrowdPacket(
            frame=frame,
            trend=trend,
            forecast=forecast,
            crowd_metrics=crowd_metrics,
            flow_metrics=flow_metrics,
            base_risk=base_risk,
            risk_state=self._risk_mapper(base_risk, flow_metrics),
            history=tuple(flow.history),
            reset=frame.tracker_reset,
        )

