"""Sequential, video-time adapter around the formal tracking and prediction classes."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable


class AnalysisCancelled(RuntimeError):
    pass


class PredictionTimelineAnalysis:
    def __init__(self, project_root: Path, *, config: dict[str, Any] | None = None, cv2_loader=None, tracker_factory=None, flow_factory=None, predictor_factory=None) -> None:
        self.root = Path(project_root)
        self.config = config or json.loads((self.root / "rpi_app" / "config.json").read_text(encoding="utf-8"))
        self.cv2_loader, self.tracker_factory = cv2_loader, tracker_factory
        self.flow_factory, self.predictor_factory = flow_factory, predictor_factory

    def _formal_factories(self):
        model = (self.root / "rpi_app" / self.config["model_path"]).resolve()
        if not model.is_file():
            raise FileNotFoundError(f"找不到 YOLO 模型：{model}；不会自动下载。")
        sys.path.insert(0, str(self.root / "rpi_app"))
        from vision.tracker import PersonTracker
        from vision.people_flow import PeopleFlowAnalyzer
        from decision.crowd_predictor import CrowdPredictor
        return (
            lambda: PersonTracker(model, self.config["confidence"], self.config["tracking"].get("tracker", "bytetrack.yaml")),
            lambda: PeopleFlowAnalyzer(self.config["flow_window_seconds"], self.config["snapshot_interval_seconds"], self.config["conflict_people_per_region"], self.config["conflict_min_total"]),
            lambda: CrowdPredictor(self.config["prediction"], self.config.get("crowd_calibration")),
        )

    def analyze(self, video_path: Path, progress: Callable[[int, int], None] | None = None, cancel_event=None) -> list[dict[str, object]]:
        if self.cv2_loader is None:
            import cv2
            cv2_module = cv2
        else:
            cv2_module = self.cv2_loader()
        if self.tracker_factory is None or self.flow_factory is None or self.predictor_factory is None:
            tracker_factory, flow_factory, predictor_factory = self._formal_factories()
        else:
            tracker_factory, flow_factory, predictor_factory = self.tracker_factory, self.flow_factory, self.predictor_factory
        capture = cv2_module.VideoCapture(str(video_path))
        if not capture.isOpened():
            capture.release(); raise RuntimeError(f"无法打开视频：{video_path}")
        try:
            fps = float(capture.get(cv2_module.CAP_PROP_FPS)) or 1.0
            total = int(capture.get(cv2_module.CAP_PROP_FRAME_COUNT))
            tracker, flow, predictor = tracker_factory(), flow_factory(), predictor_factory()
            timeline: list[dict[str, object]] = []; frame_index = 0
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise AnalysisCancelled("预测时间线分析已取消。")
                ok, frame = capture.read()
                if not ok:
                    break
                tracks = tracker.track(frame)
                width = frame.shape[1]
                left = sum(1 for track in tracks if (int(track["x1"]) + int(track["x2"])) // 2 < width // 2)
                right = len(tracks) - left
                source_time = frame_index / fps
                trend, snapshot_saved = flow.update(left, right, now=source_time)
                if snapshot_saved:
                    forecast = predictor.predict(flow.history, trend.total_people)
                    people = forecast["predicted_people"]
                    timeline.append({"time_seconds": source_time, "frame_index": frame_index, "current_system_count": trend.total_people, "left_count": left, "right_count": right, "prediction_slope": forecast["prediction_slope"], "prediction_10": people.get(10), "prediction_20": people.get(20), "prediction_30": people.get(30)})
                frame_index += 1
                if progress is not None:
                    progress(frame_index, total)
            return timeline
        finally:
            capture.release()
