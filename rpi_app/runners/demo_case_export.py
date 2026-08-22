"""Export a real formal Dashboard video and UART event timeline as a demo case."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

import cv2

from rpi_app.main import build_status
from rpi_app.communication.esp32 import build_uart_payload
from rpi_app.sources.video_source import VideoSource
from rpi_app.vision.video_runner import RISK_ORDER, TrackedFrameProcessor
from rpi_app.utils.config import load_config


ROOT = Path(__file__).resolve().parents[2]


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _event_changed(previous: Mapping[str, object] | None, current: Mapping[str, object]) -> bool:
    return previous is None or any(previous.get(key) != current.get(key) for key in current if key != "timestamp")


def export_demo_case(video: Path, case_id: str, title: str, destination: Path, config: dict[str, Any]) -> dict[str, object]:
    if not video.is_file():
        raise FileNotFoundError(f"找不到原始视频：{video}")
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"案例目录已存在且非空：{destination}；如需覆盖请先明确移走旧案例。")
    destination.mkdir(parents=True, exist_ok=True)
    runtime_config = dict(config)
    runtime_config.update({"source_type": "video", "source": str(video), "display_window": False, "save_annotated_video": False})
    runtime_config["esp32"] = {"enabled": False, "dry_run": True}
    runtime_config["teacher_runtime"] = {"enabled": False}
    source = VideoSource(video)
    processor = TrackedFrameProcessor(runtime_config, build_status)
    writer = None
    events: list[dict[str, object]] = []
    previous_payload: dict[str, object] | None = None
    previous_running = False
    running_event_count = 0
    max_people, max_crowd, highest_risk, frame_count = 0, 0.0, "NORMAL", 0
    try:
        while True:
            item = source.read()
            if item is None:
                break
            frame, source_time = item
            dashboard, status, snapshot_saved = processor.process_frame(frame, source_time)
            if writer is None:
                writer = cv2.VideoWriter(str(destination / "dashboard.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), source.fps, (dashboard.shape[1], dashboard.shape[0]))
                if not writer.isOpened():
                    raise RuntimeError("无法创建 dashboard.mp4")
                if not cv2.imwrite(str(destination / "cover.jpg"), dashboard):
                    raise RuntimeError("无法写入 cover.jpg")
            writer.write(dashboard)
            frame_count += 1
            max_people = max(max_people, int(status.get("total_people", 0)))
            max_crowd = max(max_crowd, float(status.get("crowd_index", 0.0)))
            if RISK_ORDER.get(str(status.get("vision_risk", "NORMAL")), 0) > RISK_ORDER[highest_risk]:
                highest_risk = str(status["vision_risk"])
            running = bool(status.get("running_event", False))
            if running and not previous_running:
                running_event_count += 1
            previous_running = running
            if snapshot_saved:
                payload = build_uart_payload(status)
                payload["timestamp"] = int(round(float(source_time) * 1000.0))
                if _event_changed(previous_payload, payload):
                    events.append({"time": round(float(source_time), 3), **payload})
                    previous_payload = dict(payload)
    finally:
        processor.close()
        source.close()
        if writer is not None:
            writer.release()
    if frame_count == 0 or writer is None:
        raise RuntimeError("原始视频没有可导出的帧。")
    if not events:
        events.append({"time": 0.0, **build_uart_payload({"timestamp": 0, "vision_risk": "NORMAL"})})
    (destination / "events.jsonl").write_text("".join(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n" for event in events), encoding="utf-8")
    try:
        source_video = str(video.resolve().relative_to(ROOT))
    except ValueError:
        source_video = str(video.resolve())
    summary = {
        "case_id": case_id, "title": title, "source_video": source_video,
        "duration_seconds": round(frame_count / source.fps, 3), "frame_count": frame_count,
        "source_fps": source.fps, "max_people": max_people, "max_crowd_index": round(max_crowd, 3),
        "highest_vision_risk": highest_risk, "running_event_count": running_event_count,
        "git_commit": _git_commit(), "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }
    (destination / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate one real Huian formal Dashboard demo case without ESP32 output.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--title", default="人流监测示例")
    parser.add_argument("--destination", default=None)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    video = Path(args.video).expanduser().resolve()
    destination = Path(args.destination).expanduser().resolve() if args.destination else ROOT / "demo_cases" / args.case_id
    config = load_config(args.config) if args.config else load_config()
    summary = export_demo_case(video, args.case_id, args.title, destination, config)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()