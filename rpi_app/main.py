"""Huian Loudao Raspberry Pi visual application entry point."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

import cv2

from communication.esp32 import ESP32Publisher
from decision.crowd_index import calculate_crowd_index
from decision.crowd_predictor import CrowdPredictor
from decision.risk_engine import RiskEngine
from ui.display import draw_dashboard
from utils.config import load_config, resolve_app_path
from vision.camera_runner import run_picamera2_camera
from vision.detector import PersonDetector
from vision.fire_detector import FireDetector, single_image_fire_status
from vision.people_flow import FlowTrend, PeopleFlowAnalyzer
from vision.region import count_stair_regions
from vision.video_runner import run_tracked_video


def build_status(config: dict[str, Any], trend: FlowTrend, vision_risk: str, crowd_metrics: dict[str, float], forecast: dict[str, object]) -> dict[str, object]:
    """Build the rich internal vision status; UART selects its compact subset."""
    predicted_people = forecast["predicted_people"]
    predicted_risk = forecast["predicted_risk"]
    return {
        "protocol_version": 1, "device": config["device"], "vision_risk": vision_risk,
        "crowd_index": crowd_metrics["index"], "density_score": crowd_metrics["density_score"],
        "growth_score": crowd_metrics["growth_score"], "conflict_score": crowd_metrics["conflict_score"],
        "left_people": trend.left_people, "right_people": trend.right_people, "total_people": trend.total_people,
        "occupancy_growth": trend.occupancy_growth, "direction_conflict": trend.direction_conflict,
        "prediction_valid": forecast["prediction_valid"], "prediction_slope": forecast["prediction_slope"],
        "predicted_people_10s": predicted_people.get(10), "predicted_people_20s": predicted_people.get(20),
        "predicted_people_30s": predicted_people.get(30), "predicted_risk_10s": predicted_risk.get(10),
        "predicted_risk_20s": predicted_risk.get(20), "predicted_risk_30s": predicted_risk.get(30),
        "time_to_warning": forecast["time_to_warning"], "time_to_danger": forecast["time_to_danger"],
        "crowd_calibrated": forecast["crowd_calibrated"],
        "danger_people_threshold": forecast["danger_people_threshold"],
        "timestamp": int(time.time()),
    }


def analyse_frame(frame, detector: PersonDetector, flow_analyzer: PeopleFlowAnalyzer, risk_engine: RiskEngine, predictor: CrowdPredictor, config: dict[str, Any]) -> tuple[list[dict[str, float | int | str]], dict[str, object], bool]:
    """Run the legacy single-image analysis chain unchanged."""
    detections = detector.detect(frame)
    left_people, right_people = count_stair_regions(detections, frame.shape[1])
    trend, snapshot_saved = flow_analyzer.update(left_people, right_people)
    forecast = predictor.predict(flow_analyzer.history, trend.total_people)
    crowd_metrics = calculate_crowd_index(left_people, right_people, trend.occupancy_growth, trend.direction_conflict, config["crowd_index"])
    vision_risk = risk_engine.evaluate(left_people=left_people, right_people=right_people, occupancy_growth=trend.occupancy_growth, direction_conflict=trend.direction_conflict, crowd_index=crowd_metrics["index"])
    return detections, build_status(config, trend, vision_risk, crowd_metrics, forecast), snapshot_saved


def _ensure_input(source_path: Path, source_type: str) -> None:
    if source_type not in {"image", "video"}:
        raise ValueError("source_type must be image or video for file input validation")
    if not source_path.is_file():
        raise FileNotFoundError(f"Input file not found: {source_path}")


def _create_components(config: dict[str, Any]):
    detector = PersonDetector(resolve_app_path(config["model_path"]), config["confidence"])
    flow_analyzer = PeopleFlowAnalyzer(window_seconds=config["flow_window_seconds"], sample_interval_seconds=config["snapshot_interval_seconds"], conflict_people_per_region=config["conflict_people_per_region"], conflict_min_total=config["conflict_min_total"])
    return detector, flow_analyzer, RiskEngine(config["warning_people"], config["danger_people"]), CrowdPredictor(config["prediction"], config.get("crowd_calibration"))


def _write_image(output_path: Path, image) -> bool:
    success, encoded = cv2.imencode(output_path.suffix or ".jpg", image)
    if success:
        encoded.tofile(str(output_path))
    return bool(success)


def run_image(config: dict[str, Any], source_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    frame = cv2.imread(str(source_path))
    if frame is None:
        raise RuntimeError(f"Unable to read image: {source_path}")
    detector, flow_analyzer, risk_engine, predictor = _create_components(config)
    detections, status, _ = analyse_frame(frame, detector, flow_analyzer, risk_engine, predictor, config)
    fire_detector = FireDetector(config.get("fire_detection", {}))
    fire_result = fire_detector.detect(frame)
    status.update(single_image_fire_status(fire_result, fire_detector.enabled))
    publisher = ESP32Publisher(config.get("esp32"), legacy_dry_run=bool(config.get("esp32_dry_run", True)))
    try:
        publisher.send_status(status)
    finally:
        publisher.close()
    output_path = output_dir / f"{source_path.stem}_annotated.jpg"
    annotated = draw_dashboard(frame, detections, status, display=config.get("display", {}), ui_context={
        "fire_detections": fire_result["detections"],
        "crowd_calibration": config.get("crowd_calibration", {}),
    })
    if not _write_image(output_path, annotated):
        raise RuntimeError(f"Unable to write annotated image: {output_path}")
    print(f"Saved annotated image: {output_path}")
    if config.get("display_window", False):
        cv2.imshow("Huian Loudao", annotated)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


def _run_config(config: dict[str, Any]) -> None:
    source_type = str(config["source_type"]).lower()
    output_dir = resolve_app_path(config.get("output_dir", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    if source_type == "camera":
        run_picamera2_camera(config, output_dir, build_status)
        return
    if source_type not in {"image", "video"}:
        raise ValueError("source_type must be image, video, or camera")
    source_path = resolve_app_path(config["source"])
    _ensure_input(source_path, source_type)
    if source_type == "image":
        run_image(config, source_path, output_dir)
    else:
        run_tracked_video(config, source_path, output_dir, build_status)


def cli_main() -> None:
    parser = argparse.ArgumentParser(description="Huian Loudao visual safety system")
    parser.add_argument("--config", default=None, help="JSON configuration path")
    parser.add_argument("--source", default=None, help="override image or video source")
    parser.add_argument("--source-type", choices=["image", "video", "camera"], default=None)
    parser.add_argument("--no-display", action="store_true", help="disable OpenCV window")
    args = parser.parse_args()
    config = load_config(args.config) if args.config else load_config()
    if args.source is not None:
        config["source"] = args.source
    if args.source_type is not None:
        config["source_type"] = args.source_type
    if args.no_display:
        config["display_window"] = False
    _run_config(config)


def main() -> None:
    _run_config(load_config())


if __name__ == "__main__":
    cli_main()