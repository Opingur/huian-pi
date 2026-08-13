"""Temporary IMX219 person-to-ESP32 UART hardware integration test.

This tool is independent from rpi_app/main.py and sends protocol-v1 JSON only.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from communication.esp32 import ESP32Publisher
from vision.detector import PersonDetector

DEFAULT_MODEL = APP_DIR.parent / "models" / "yolov8n.pt"


def build_person_test_status(total_people: int) -> dict[str, object]:
    """Build every field required by the existing ESP32 protocol-v1 parser."""
    return {
        "protocol_version": 1,
        "timestamp": int(time.time()),
        "vision_risk": "NORMAL",
        "crowd_index": 0.0,
        "total_people": int(total_people),
        "direction_conflict": False,
        "vision_fire_suspected": False,
        "vision_smoke_suspected": False,
        "vision_fire_confidence": 0.0,
        "vision_smoke_confidence": 0.0,
    }


def run(model_path: Path, confidence: float, interval_seconds: float) -> None:
    try:
        from picamera2 import Picamera2
    except ImportError as error:
        raise RuntimeError("This IMX219 integration test requires Picamera2 on Raspberry Pi.") from error

    detector = PersonDetector(model_path, confidence)
    publisher = ESP32Publisher({
        "enabled": True,
        "dry_run": False,
        "port": "/dev/ttyAMA0",
        "baud": 115200,
        # This tool itself schedules one capture/inference/send per second.
        "send_interval_seconds": 0.01,
    })
    camera = None
    started = False
    try:
        camera = Picamera2()
        camera.configure(camera.create_video_configuration(main={
            "size": (1280, 720),
            "format": "RGB888",
        }))
        camera.start()
        started = True
        next_due = time.monotonic()
        while True:
            now = time.monotonic()
            if now < next_due:
                time.sleep(min(0.05, next_due - now))
                continue
            # Keep a stable 1 Hz schedule even if one inference is slow.
            next_due = max(next_due + interval_seconds, time.monotonic())
            frame_rgb = camera.capture_array()
            if frame_rgb is None or frame_rgb.ndim != 3 or frame_rgb.shape[2] != 3:
                raise RuntimeError("Picamera2 RGB888 capture did not return a three-channel frame")
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            people = len(detector.detect(frame_bgr))  # PersonDetector calls YOLO with classes=[0].
            sent = publisher.send_status(build_person_test_status(people))
            print(f"[PERSON TEST] people={people} {'sent' if sent else 'not-sent'}", flush=True)
    except KeyboardInterrupt:
        print("[PERSON TEST] stopped", flush=True)
    finally:
        publisher.close()
        if camera is not None:
            try:
                if started:
                    camera.stop()
            finally:
                camera.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Temporary IMX219 person-to-ESP32 UART integration test")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--confidence", type=float, default=0.35)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.interval <= 0:
        raise ValueError("--interval must be positive")
    run(args.model, args.confidence, args.interval)


if __name__ == "__main__":
    main()