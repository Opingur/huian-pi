"""慧安楼道电脑端视觉安全系统入口。按 Q 键退出。"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

import cv2

from decision.crowd_index import calculate_crowd_index
from decision.risk_engine import RiskEngine
from sensors.sensor_data import SensorData
from ui.display import draw_dashboard
from utils.config import load_config
from vision.detector import PersonDetector, resolve_model_path
from vision.people_flow import PeopleFlowAnalyzer
from vision.region import count_stair_regions


def build_status(config, trend, risk: str, crowd_metrics: dict[str, float], sensors: SensorData) -> dict[str, object]:
    """系统对 ESP32、Web 和数据记录共用的统一 JSON 数据结构。"""
    return {
        "device": config["device"],
        "crowd_index": crowd_metrics["index"],
        "density_score": crowd_metrics["density_score"],
        "growth_score": crowd_metrics["growth_score"],
        "conflict_score": crowd_metrics["conflict_score"],
        "total_people": trend.total_people,
        "left_people": trend.left_people,
        "right_people": trend.right_people,
        "crowd_level": risk,
        "risk_level": risk,
        "direction_conflict": trend.direction_conflict,
        "occupancy_growth": trend.occupancy_growth,
        "sensors": sensors.to_dict(),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    config = load_config(Path(__file__).with_name("config.json"))
    model_path = project_root / config["model_path"]
    detector = PersonDetector(resolve_model_path(str(model_path)), config["confidence"])
    flow_analyzer = PeopleFlowAnalyzer(
        window_seconds=config["flow_window_seconds"],
        sample_interval_seconds=config["snapshot_interval_seconds"],
        conflict_people_per_region=config["conflict_people_per_region"],
        conflict_min_total=config["conflict_min_total"],
    )
    risk_engine = RiskEngine(config["warning_people"], config["danger_people"])
    sensors = SensorData()
    camera = cv2.VideoCapture(config["camera_index"])

    if not camera.isOpened():
        raise RuntimeError(f"无法打开摄像头：{config['camera_index']}")

    try:
        while True:
            success, frame = camera.read()
            if not success:
                print("摄像头读取失败，程序结束。")
                break

            detections = detector.detect(frame)
            left_people, right_people = count_stair_regions(detections, frame.shape[1])
            trend, snapshot_saved = flow_analyzer.update(left_people, right_people)
            crowd_metrics = calculate_crowd_index(
                left_people, right_people, trend.occupancy_growth,
                trend.direction_conflict, config["crowd_index"],
            )
            risk = risk_engine.evaluate(
                left_people=left_people,
                right_people=right_people,
                occupancy_growth=trend.occupancy_growth,
                direction_conflict=trend.direction_conflict,
                crowd_index=crowd_metrics["index"],
                smoke=sensors.smoke,
                temperature=sensors.temperature,
                smoke_fire_threshold=config["smoke_fire_threshold"],
                temperature_fire_threshold=config["temperature_fire_threshold"],
            )
            status = build_status(config, trend, risk, crowd_metrics, sensors)
            if snapshot_saved:
                print(json.dumps(status, ensure_ascii=False))

            cv2.imshow("Huian Loudao", draw_dashboard(frame, detections, status))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
