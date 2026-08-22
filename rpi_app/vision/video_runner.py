"""Shared tracked-frame pipeline and OpenCV video runner."""

from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path
from typing import Any, Callable

import cv2

from communication.esp32 import ESP32Publisher
from decision.alarm import AlarmDebouncer
from decision.crowd_index import calculate_crowd_index
from decision.crowd_predictor import CrowdPredictor
from decision.flow_analysis import FlowRiskAnalyzer
from decision.risk_engine import RiskEngine
from ui.display import draw_dashboard
from ui.explain_panel import ExplainTargetLock
from ui.flow_group_visualizer import build_flow_groups
from vision.fire_detector import FireDetector, FireEvidenceTracker
from vision.live_workers import LatestFireWorker, LatestFrameWorker
from vision.people_flow import PeopleFlowAnalyzer
from vision.running_detector import RunningDetector, aggregate_running
from vision.tracker import PersonTracker
from sources.video_source import VideoSource
from services.runtime_snapshot import RuntimeSnapshotPublisher
from vision.trajectory import TrajectoryAnalyzer


RISK_ORDER = {"NORMAL": 0, "WARNING": 1, "CROWD": 2, "DANGER": 3}
def _source_time(capture, frame_index: int, fps: float) -> float:
    position_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC))
    return position_ms / 1000.0 if position_ms > 0 else frame_index / max(fps, 1.0)


def _write_summary(path: Path, summary: dict[str, object]) -> None:
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _apply_flow_risk(base_risk: str, flow_metrics: dict[str, object]) -> str:
    """All people-flow risks use CROWD; fire is a separate ESP32 safety path."""
    if flow_metrics.get("convergence_risk"):
        return "CROWD"
    if (
        base_risk in {"WARNING", "CROWD", "DANGER"}
        or flow_metrics.get("single_flow_crowd_risk")
        or flow_metrics.get("predicted_single_flow_warning")
    ):
        return "CROWD"
    return "NORMAL"


def _finalize_visual_alarm(vision_risk: str, debounced_alarm: str, alarm_reason: str) -> tuple[str, str, str]:
    if debounced_alarm == "RED":
        return "CROWD", "YELLOW", alarm_reason
    if vision_risk in {"WARNING", "CROWD"}:
        return vision_risk, "YELLOW", "vision_risk_warning"
    return vision_risk, "NONE", "none"


class TrackedFrameProcessor:
    """Shared BGR pipeline; camera mode uses latest-frame workers, offline remains synchronous."""

    def __init__(self, config: dict[str, Any], build_status: Callable[..., dict[str, object]]) -> None:
        self.config = config
        self.build_status = build_status
        self.tracker = PersonTracker(
            Path(__file__).resolve().parents[1] / config["model_path"],
            config["confidence"],
            config["tracking"].get("tracker", "bytetrack.yaml"),
        )
        self.flow = PeopleFlowAnalyzer(
            window_seconds=config["flow_window_seconds"],
            sample_interval_seconds=config["snapshot_interval_seconds"],
            conflict_people_per_region=config["conflict_people_per_region"],
            conflict_min_total=config["conflict_min_total"],
        )
        self.predictor = CrowdPredictor(config["prediction"], config.get("crowd_calibration"))
        self.risk_engine = RiskEngine(config["warning_people"], config["danger_people"])
        self.trajectories = TrajectoryAnalyzer(config["tracking"])
        self.running = RunningDetector(config.get("running_detection"))
        self.flow_risk = FlowRiskAnalyzer(config.get("flow_risk", {}))
        self.alarms = AlarmDebouncer(config["alarm"])
        self.explain_lock = ExplainTargetLock(config.get("display", {}).get("explain_lock_seconds", 1.0))
        self.publisher = ESP32Publisher(config.get("esp32"), legacy_dry_run=bool(config.get("esp32_dry_run", True)))
        self.runtime_snapshot = RuntimeSnapshotPublisher.from_config(config.get("teacher_runtime"))
        self.esp32_status = None
        self.esp32_status_stale = True
        self.fire_detector = FireDetector(config.get("fire_detection", {}))
        self.fire_evidence = FireEvidenceTracker(config.get("fire_detection", {}), self.fire_detector.enabled)
        self._person_worker: LatestFrameWorker | None = None
        self._fire_worker: LatestFireWorker | None = None
        self._live_person_version = -1
        self._latest_live_analysis: dict[str, object] | None = None

    def _poll_esp32(self) -> None:
        # Serial reads only drain complete kernel-buffered lines; never reopen or reparse UART.
        self.esp32_status = self.publisher.poll_esp32_status()
        self.esp32_status_stale = self.publisher.esp32_status_is_stale()

    def _log_fire_inference(self, fire_status: dict[str, object]) -> None:
        sources = ",".join(self.fire_evidence.last_result.get("inference_sources", [])) or "none"
        print(
            "Fire inference: "
            f"raw_fire={fire_status['fire_detected_raw']} "
            f"stable_fire={fire_status['vision_fire_suspected']} "
            f"best_fire_confidence={fire_status['vision_fire_confidence']:.3f} "
            f"detections={len(self.fire_evidence.last_result.get('detections', []))} source={sources}",
            flush=True,
        )

    def _analyse_tracks(self, tracks: list[dict[str, object]], frame_shape: tuple[int, ...], source_timestamp: float) -> dict[str, object]:
        frame_height, frame_width = frame_shape[:2]
        left_people = sum(1 for track in tracks if (int(track["x1"]) + int(track["x2"])) // 2 < frame_width // 2)
        right_people = len(tracks) - left_people
        trend, snapshot_saved = self.flow.update(left_people, right_people, now=source_timestamp)
        forecast = self.predictor.predict(self.flow.history, trend.total_people)
        motions_by_id = self.trajectories.update(
            tracks, frame_width, frame_height, source_timestamp, self.config.get("conflict_zone", []),
        )
        running_by_id = self.running.update(tracks, source_timestamp)
        for track_id, running in running_by_id.items():
            motions_by_id.setdefault(track_id, {}).update(running)
        flow_groups = build_flow_groups(motions_by_id)
        explain_target_id = self.explain_lock.choose(
            motions_by_id, source_timestamp, self.config.get("display", {}).get("explain_track_id"),
        )
        flow_metrics = self.flow_risk.analyze(list(motions_by_id.values()), forecast, flow_groups)
        crowd_metrics = calculate_crowd_index(
            left_people, right_people, trend.occupancy_growth, trend.direction_conflict,
            self.config["crowd_index"], flow_metrics["convergence_score"],
        )
        base_risk = self.risk_engine.evaluate(
            left_people, right_people, trend.occupancy_growth, trend.direction_conflict, crowd_metrics["index"],
        )
        vision_risk = _apply_flow_risk(base_risk, flow_metrics)
        debounced_alarm, alarm_reason = self.alarms.update(
            source_timestamp, vision_risk == "CROWD", False,
        )
        vision_risk, visual_alarm, alarm_reason = _finalize_visual_alarm(vision_risk, debounced_alarm, alarm_reason)
        status = self.build_status(self.config, trend, vision_risk, crowd_metrics, forecast)
        status.update(flow_metrics)
        status.update({
            "source_time": round(source_timestamp, 3),
            "visual_alarm": visual_alarm,
            "alarm_reason": alarm_reason,
        })
        status.update(aggregate_running(running_by_id))
        return {
            "tracks": tracks,
            "status": status,
            "snapshot_saved": snapshot_saved,
            "motions": motions_by_id,
            "flow_groups": flow_groups,
            "explain_target_id": explain_target_id,
            "frame_shape": frame_shape,
        }

    def _render(self, frame_bgr, analysis: dict[str, object], fire_status: dict[str, object]) -> tuple[object, dict[str, object], bool]:
        status = dict(analysis["status"])
        status.update(fire_status)
        status.update({
            "mode": "live",
            "camera_online": str(self.config.get("source_type", "")).lower() == "camera",
            "esp32_online": bool(self.esp32_status and not self.esp32_status_stale),
            "current_event": status.get("alarm_reason") or "正常监测",
        })
        annotated = draw_dashboard(
            frame_bgr, analysis["tracks"], status,
            conflict_zone=self.config.get("conflict_zone", []),
            motions=analysis["motions"], display=self.config.get("display", {}),
            ui_context={
                "motions": analysis["motions"],
                "flow_groups": analysis["flow_groups"],
                "explain_target_id": analysis["explain_target_id"],
                "crowd_calibration": self.config.get("crowd_calibration", {}),
                "prediction_history": list(self.flow.history),
                "crowd_index_config": self.config["crowd_index"],
                "frame_width": frame_bgr.shape[1],
                "frame_height": frame_bgr.shape[0],
                "fire_detections": fire_status.get("fire_display_detections", []),
                "esp32_status": self.esp32_status,
                "esp32_status_stale": self.esp32_status_stale,
                "esp32_configured": self.publisher.enabled and not self.publisher.dry_run,
            },
        )
        self.runtime_snapshot.publish(status, annotated, source_time=float(status.get("source_time", 0.0)))
        return annotated, status, bool(analysis["snapshot_saved"])

    def process_frame(self, frame_bgr, source_timestamp: float) -> tuple[object, dict[str, object], bool]:
        """Offline image/video path: preserve the original fully synchronous processing order."""
        self._poll_esp32()
        fire_inferred = self.fire_evidence.should_infer(source_timestamp)
        if fire_inferred:
            self.fire_evidence.record(self.fire_detector.detect(frame_bgr), source_timestamp)
        fire_status = self.fire_evidence.status(source_timestamp)
        if fire_inferred:
            self._log_fire_inference(fire_status)
        analysis = self._analyse_tracks(self.tracker.track(frame_bgr), frame_bgr.shape, source_timestamp)
        return self._render(frame_bgr, analysis, fire_status)

    def enable_live_async(self) -> None:
        """Start live-only latest-frame workers. One worker owns ByteTrack state."""
        if self._person_worker is not None:
            return
        live = self.config.get("live_processing", {})
        person_interval = float(live.get("person_interval_seconds", 0.25))
        fire_interval = float(self.config.get("fire_detection", {}).get("interval_seconds", 1.0))
        self._person_worker = LatestFrameWorker("person", lambda frame, _timestamp: self.tracker.track(frame), person_interval)
        self._fire_worker = LatestFireWorker(self.fire_detector, self.fire_evidence, fire_interval)

    def process_live_frame(self, frame_bgr, source_timestamp: float) -> tuple[object, dict[str, object], bool]:
        """Render immediately from the latest completed AI results; never wait for inference."""
        self.enable_live_async()
        assert self._person_worker is not None
        assert self._fire_worker is not None
        self._poll_esp32()
        self._person_worker.submit(frame_bgr, source_timestamp)
        self._fire_worker.submit(frame_bgr, source_timestamp)
        person = self._person_worker.snapshot()
        snapshot_saved = False
        if person.version != self._live_person_version and person.result is not None:
            self._latest_live_analysis = self._analyse_tracks(person.result, frame_bgr.shape, float(person.source_timestamp))
            self._live_person_version = person.version
            snapshot_saved = bool(self._latest_live_analysis["snapshot_saved"])
        if self._latest_live_analysis is None:
            # A deterministic empty result is only a display placeholder until the first worker result arrives.
            self._latest_live_analysis = self._analyse_tracks([], frame_bgr.shape, source_timestamp)
            self._latest_live_analysis["snapshot_saved"] = False
        fire_status = self._fire_worker.status(source_timestamp)
        annotated, status, _ = self._render(frame_bgr, self._latest_live_analysis, fire_status)
        return annotated, status, snapshot_saved

    def performance_snapshot(self, source_timestamp: float) -> dict[str, object]:
        person = self._person_worker.snapshot() if self._person_worker is not None else None
        fire = self._fire_worker.snapshot() if self._fire_worker is not None else None
        latest_frame_age_ms = None
        if person is not None and person.source_timestamp is not None:
            latest_frame_age_ms = round(max(0.0, source_timestamp - person.source_timestamp) * 1000.0, 1)
        return {
            "person_inference_ms": None if person is None else person.inference_ms,
            "fire_inference_ms": None if fire is None else fire.inference_ms,
            "fire_worker_busy": False if fire is None else fire.busy,
            "latest_frame_age_ms": latest_frame_age_ms,
            "person_worker_error": None if person is None else person.error,
            "fire_worker_error": None if fire is None else fire.error,
        }

    def close(self) -> None:
        if self._person_worker is not None:
            self._person_worker.close()
            self._person_worker = None
        if self._fire_worker is not None:
            self._fire_worker.close()
            self._fire_worker = None
        self.publisher.close()
def run_tracked_video(
    config: dict[str, Any],
    source_path: Path,
    output_dir: Path,
    build_status: Callable[..., dict[str, object]],
) -> None:
    """Read an OpenCV video and send each BGR frame to TrackedFrameProcessor."""
    output_dir.mkdir(parents=True, exist_ok=True)
    source = VideoSource(source_path)
    fps = source.fps
    frame_count = source.frame_count
    width = source.width
    height = source.height
    processor = TrackedFrameProcessor(config, build_status)
    status_path = output_dir / "status.jsonl"
    output_name = config.get("output_video_name", f"{source_path.stem}_annotated.mp4")
    output_path = output_dir / str(output_name)
    writer = None
    processed_frames = 0
    frame_index = 0
    totals: list[int] = []
    unique_ids: set[int] = set()
    max_tracked = 0
    prediction_valid_from = None
    max_crowd_index = 0.0
    highest_risk = "NORMAL"
    alarm_events = {"YELLOW": 0, "RED": 0}
    alarm_durations = {"YELLOW": 0.0, "RED": 0.0}
    previous_alarm = "NONE"
    previous_source_time = 0.0
    min_convergence_eta = None
    start_wall = time.perf_counter()

    try:
        with status_path.open("w", encoding="utf-8") as status_file:
            while True:
                item = source.read()
                if item is None:
                    break
                frame_bgr, source_timestamp = item
                annotated, status, snapshot_saved = processor.process_frame(frame_bgr, source_timestamp)
                if config.get("save_annotated_video", False):
                    if writer is None:
                        writer = cv2.VideoWriter(
                            str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps,
                            (annotated.shape[1], annotated.shape[0]),
                        )
                        if not writer.isOpened():
                            raise RuntimeError(f"Unable to create annotated video: {output_path}")
                    writer.write(annotated)
                if snapshot_saved:
                    processor.publisher.send_status(status, source_timestamp=source_timestamp)
                    status_file.write(json.dumps(status, ensure_ascii=False) + "\n")

                processed_frames += 1
                frame_index += 1
                totals.append(int(status["total_people"]))
                max_tracked = max(max_tracked, int(status["tracked_people"]))
                max_crowd_index = max(max_crowd_index, float(status["crowd_index"]))
                if status["prediction_valid"] and prediction_valid_from is None:
                    prediction_valid_from = round(source_timestamp, 3)
                if RISK_ORDER[str(status["vision_risk"])] > RISK_ORDER[highest_risk]:
                    highest_risk = str(status["vision_risk"])
                visual_alarm = str(status["visual_alarm"])
                if visual_alarm != previous_alarm and visual_alarm in alarm_events:
                    alarm_events[visual_alarm] += 1
                if previous_alarm in alarm_durations:
                    alarm_durations[previous_alarm] += max(0.0, source_timestamp - previous_source_time)
                previous_alarm = visual_alarm
                previous_source_time = source_timestamp
                if status["convergence_eta"] is not None:
                    eta = float(status["convergence_eta"])
                    min_convergence_eta = eta if min_convergence_eta is None else min(min_convergence_eta, eta)
                if config.get("display_window", False):
                    cv2.imshow("Huian Loudao", annotated)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
    finally:
        processor.close()
        source.close()
        if writer is not None:
            writer.release()
        if config.get("display_window", False):
            cv2.destroyAllWindows()

    elapsed_wall = time.perf_counter() - start_wall
    try:
        import torch
        torch_version = torch.__version__
    except ImportError:
        torch_version = "unavailable"
    try:
        import ultralytics
        ultralytics_version = ultralytics.__version__
    except ImportError:
        ultralytics_version = "unavailable"
    _write_summary(output_dir / "summary.json", {
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "torch_version": torch_version,
        "ultralytics_version": ultralytics_version,
        "video_duration_seconds": round(frame_count / fps, 3) if fps else None,
        "source_fps": fps,
        "resolution": [width, height],
        "processed_frames": processed_frames,
        "wall_time_seconds": round(elapsed_wall, 3),
        "processing_fps": round(processed_frames / elapsed_wall, 3) if elapsed_wall else None,
        "max_people": max(totals, default=0),
        "average_people": round(sum(totals) / len(totals), 3) if totals else 0,
        "max_tracked_people": max_tracked,
        "prediction_valid_from_source_time": prediction_valid_from,
        "max_crowd_index": round(max_crowd_index, 3),
        "highest_vision_risk": highest_risk,
        "yellow_event_count": alarm_events["YELLOW"],
        "yellow_duration_seconds": round(alarm_durations["YELLOW"], 3),
        "red_event_count": alarm_events["RED"],
        "red_duration_seconds": round(alarm_durations["RED"], 3),
        "minimum_convergence_eta": min_convergence_eta,
        "annotated_video": str(output_path) if writer is not None else None,
        "status_jsonl": str(status_path),
    })
