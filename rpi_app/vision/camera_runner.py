"""Picamera2 live input adapter for Raspberry Pi CSI cameras."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import cv2

from ui.startup_screen import STARTUP_INITIALIZING, StartupScreen, startup_failure_message
from vision.frame_color import picamera_rgb888_capture_array_to_bgr
from vision.video_runner import TrackedFrameProcessor


def _configure_live_window(config: dict[str, Any]) -> str | None:
    """Create a plain OpenCV window; fullscreen is a live configuration choice."""
    if not config.get("display_window", False):
        return None
    display = config.get("display", {})
    window_name = str(display.get("window_name", "Huian Loudao"))
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL)
    if bool(display.get("fullscreen", False)):
        cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    return window_name


def _print_live_performance(frames: int, elapsed_seconds: float, processor: TrackedFrameProcessor, source_timestamp: float) -> None:
    perf = processor.performance_snapshot(source_timestamp)
    person_ms = "n/a" if perf["person_inference_ms"] is None else f"{perf['person_inference_ms']:.0f}"
    fire_ms = "n/a" if perf["fire_inference_ms"] is None else f"{perf['fire_inference_ms']:.0f}"
    age_ms = "n/a" if perf["latest_frame_age_ms"] is None else f"{perf['latest_frame_age_ms']:.0f}"
    print(
        f"Live perf: display_fps={frames / max(elapsed_seconds, 0.001):.1f} "
        f"person_inference_ms={person_ms} fire_inference_ms={fire_ms} "
        f"fire_worker_busy={int(bool(perf['fire_worker_busy']))} latest_frame_age_ms={age_ms}",
        flush=True,
    )
    for worker_name in ("person_worker_error", "fire_worker_error"):
        if perf[worker_name]:
            print(f"Live worker error ({worker_name}): {perf[worker_name]}", flush=True)


def run_picamera2_camera(
    config: dict[str, Any],
    output_dir: Path,
    build_status: Callable[..., dict[str, object]],
) -> None:
    """Show Splash first, then initialise the existing camera and live-processing chain."""
    camera_config = config.get("camera", {})
    width = int(camera_config.get("width", 1280))
    height = int(camera_config.get("height", 720))
    pixel_format = str(camera_config.get("format", "RGB888"))
    if pixel_format != "RGB888":
        raise ValueError("camera.format currently supports RGB888 only")

    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "camera_status.jsonl"
    window_name = _configure_live_window(config)
    startup = StartupScreen(window_name, config.get("display", {}))
    startup.show(STARTUP_INITIALIZING)
    camera = None
    started = False
    processor = None
    start_time = None
    try:
        try:
            from picamera2 import Picamera2
        except ImportError as error:
            raise RuntimeError(
                "source_type=camera requires Picamera2 on Raspberry Pi; image/video modes do not need it."
            ) from error

        startup.show("正在连接摄像头…")
        camera = Picamera2()
        camera.configure(camera.create_video_configuration(main={"size": (width, height), "format": pixel_format}))
        camera.start()
        started = True
        startup.show("正在启动视觉系统…")
        processor = TrackedFrameProcessor(config, build_status)
        startup.show("实时监测启动…")
        start_time = time.monotonic()
        live = config.get("live_processing", {})
        perf_interval = float(live.get("performance_log_interval_seconds", 2.0))
        performance_enabled = bool(live.get("performance_log_enabled", True))
        last_perf_time = start_time
        perf_frames = 0
        with status_path.open("w", encoding="utf-8") as status_file:
            while True:
                frame_rgb = camera.capture_array()
                if frame_rgb is None or frame_rgb.ndim != 3 or frame_rgb.shape[2] != 3:
                    raise RuntimeError("Picamera2 RGB888 capture did not return a three-channel frame")
                # Picamera2 RGB888 capture_array is already [B, G, R] for OpenCV; do not swap again.
                frame_bgr = picamera_rgb888_capture_array_to_bgr(frame_rgb)
                source_timestamp = time.monotonic() - float(start_time)
                annotated, status, snapshot_saved = processor.process_live_frame(frame_bgr, source_timestamp)
                if snapshot_saved:
                    processor.publisher.send_status(status, source_timestamp=source_timestamp)
                    status_file.write(json.dumps(status, ensure_ascii=False) + "\n")
                perf_frames += 1
                now = time.monotonic()
                if performance_enabled and now - last_perf_time >= perf_interval:
                    _print_live_performance(perf_frames, now - last_perf_time, processor, source_timestamp)
                    last_perf_time = now
                    perf_frames = 0
                if window_name is not None:
                    cv2.imshow(window_name, annotated)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (27, ord("q")):
                        break
    except KeyboardInterrupt:
        raise
    except Exception as error:
        startup.show(startup_failure_message(error), error=True)
        startup.wait_for_exit()
        raise
    finally:
        if processor is not None:
            processor.close()
        if window_name is not None:
            cv2.destroyAllWindows()
        if camera is not None:
            try:
                if started:
                    camera.stop()
            finally:
                camera.close()