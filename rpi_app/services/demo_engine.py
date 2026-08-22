"""Pi-owned dashboard-video playback and ESP32 event timeline for teacher demos."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable, Mapping

import cv2

from rpi_app.communication.esp32 import ESP32Publisher, build_uart_payload


@dataclass(frozen=True)
class DemoCase:
    case_id: str
    title: str
    directory: Path
    dashboard_path: Path
    events_path: Path
    summary: dict[str, object]

    @property
    def duration_seconds(self) -> float:
        return float(self.summary.get("duration_seconds", 0.0) or 0.0)


def scan_demo_cases(root: Path) -> list[DemoCase]:
    """Return only complete, parseable cases; unknown summary fields are retained."""
    cases: list[DemoCase] = []
    if not root.is_dir():
        return cases
    for summary_path in sorted(root.glob("*/summary.json")):
        directory = summary_path.parent
        dashboard_path, events_path, cover_path = directory / "dashboard.mp4", directory / "events.jsonl", directory / "cover.jpg"
        if not (dashboard_path.is_file() and events_path.is_file() and cover_path.is_file()):
            continue
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(summary, dict):
            continue
        case_id = str(summary.get("case_id") or directory.name).strip()
        if not case_id:
            continue
        cases.append(DemoCase(case_id, str(summary.get("title") or case_id), directory, dashboard_path, events_path, summary))
    return cases


def load_demo_events(path: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        try:
            event = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(event, dict) and isinstance(event.get("time"), (int, float)):
            events.append(dict(event))
    return sorted(events, key=lambda item: float(item["time"]))


def normal_demo_status() -> dict[str, object]:
    return {
        "protocol_version": 1, "timestamp": 0, "vision_risk": "NORMAL", "crowd_index": 0.0,
        "total_people": 0, "direction_conflict": False, "vision_fire_suspected": False,
        "vision_smoke_suspected": False, "vision_fire_confidence": 0.0,
        "vision_smoke_confidence": 0.0, "running_event": False, "running_count": 0,
    }


class DemoEngine:
    """Own one video clock so JPEG playback and UART events never depend on Windows timing."""

    def __init__(
        self,
        cases_root: Path,
        publisher: ESP32Publisher,
        *,
        capture_factory: Callable[[Path], Any] | None = None,
        jpeg_encoder: Callable[[Any], bytes] | None = None,
        clock: Callable[[], float] = time.monotonic,
        auto_thread: bool = True,
    ) -> None:
        self.cases_root = cases_root.resolve()
        self.publisher = publisher
        self.capture_factory = capture_factory or (lambda path: cv2.VideoCapture(str(path)))
        self.jpeg_encoder = jpeg_encoder or self._encode_jpeg
        self.clock = clock
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._closed = False
        self._thread: threading.Thread | None = None
        self._capture: Any | None = None
        self._case: DemoCase | None = None
        self._events: list[dict[str, object]] = []
        self._event_cursor = 0
        self._frame_index = 0
        self._fps = 10.0
        self._next_frame_at = 0.0
        self._state = "stopped"
        self._position = 0.0
        self._latest_jpeg: bytes | None = None
        self._latest_status = normal_demo_status()
        self._last_error = ""
        if auto_thread:
            self._thread = threading.Thread(target=self._run, name="huian-demo-engine", daemon=True)
            self._thread.start()

    @staticmethod
    def _encode_jpeg(frame) -> bytes:
        success, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not success:
            raise RuntimeError("无法编码 Dashboard JPEG")
        return encoded.tobytes()

    def cases(self) -> list[dict[str, object]]:
        return [
            {"case_id": item.case_id, "title": item.title, "duration": item.duration_seconds, "cover": f"/api/cases/{item.case_id}/cover.jpg"}
            for item in scan_demo_cases(self.cases_root)
        ]

    def _find_case(self, case_id: str) -> DemoCase:
        for item in scan_demo_cases(self.cases_root):
            if item.case_id == case_id:
                return item
        raise ValueError(f"未找到有效演示案例：{case_id}")

    def _release_capture(self) -> None:
        if self._capture is not None:
            release = getattr(self._capture, "release", None)
            if release is not None:
                release()
            self._capture = None

    def _reset_publisher_timing(self) -> None:
        reset = getattr(self.publisher, "reset_send_interval", None)
        if callable(reset):
            reset()

    def _send(self, event: Mapping[str, object], position: float) -> None:
        payload = normal_demo_status()
        payload.update(event)
        payload["timestamp"] = int(round(float(position) * 1000.0))
        self._latest_status = dict(payload)
        self.publisher.send_status(payload, source_timestamp=float(position))

    def _dispatch_events(self) -> None:
        while self._event_cursor < len(self._events) and float(self._events[self._event_cursor]["time"]) <= self._position + 1e-6:
            event = self._events[self._event_cursor]
            self._send(event, float(event["time"]))
            self._event_cursor += 1

    def start(self, case_id: str) -> dict[str, object]:
        with self._lock:
            case = self._find_case(case_id)
            self._release_capture()
            capture = self.capture_factory(case.dashboard_path)
            if not bool(getattr(capture, "isOpened", lambda: True)()):
                raise RuntimeError(f"无法打开演示视频：{case.dashboard_path}")
            self._capture, self._case = capture, case
            self._events = load_demo_events(case.events_path)
            self._event_cursor, self._frame_index, self._position = 0, 0, 0.0
            self._fps = float(getattr(capture, "get", lambda _key: 0)(cv2.CAP_PROP_FPS) or case.summary.get("source_fps") or 10.0)
            self._next_frame_at = self.clock()
            self._state, self._last_error = "playing", ""
            self._latest_status = normal_demo_status()
            self._reset_publisher_timing()
            self._dispatch_events()
            if self._event_cursor == 0:
                self._send(normal_demo_status(), 0.0)
            self._wake.set()
            return self.state()

    def pause(self) -> dict[str, object]:
        with self._lock:
            if self._state == "playing":
                self._state = "paused"
            return self.state()

    def resume(self) -> dict[str, object]:
        with self._lock:
            if self._state == "paused":
                self._state, self._next_frame_at = "playing", self.clock()
                self._wake.set()
            return self.state()

    def restart(self) -> dict[str, object]:
        with self._lock:
            if self._case is None:
                raise ValueError("当前没有可重播的演示案例。")
            case_id = self._case.case_id
        return self.start(case_id)

    def stop(self) -> dict[str, object]:
        with self._lock:
            self._release_capture()
            self._state, self._position, self._event_cursor = "stopped", 0.0, 0
            self._reset_publisher_timing()
            self._send(normal_demo_status(), 0.0)
            return self.state()

    def tick(self) -> float:
        """Advance at most one source-video frame; public for deterministic tests."""
        with self._lock:
            if self._state != "playing" or self._capture is None:
                return 0.08
            now = self.clock()
            if now < self._next_frame_at:
                return min(0.08, self._next_frame_at - now)
            success, frame = self._capture.read()
            if not success:
                self._state = "stopped"
                self._release_capture()
                self._reset_publisher_timing()
                self._send(normal_demo_status(), 0.0)
                return 0.08
            self._frame_index += 1
            position_ms = float(getattr(self._capture, "get", lambda _key: 0)(cv2.CAP_PROP_POS_MSEC) or 0.0)
            self._position = position_ms / 1000.0 if position_ms > 0 else self._frame_index / max(self._fps, 1.0)
            self._latest_jpeg = self.jpeg_encoder(frame)
            self._dispatch_events()
            self._next_frame_at = now + 1.0 / max(self._fps, 1.0)
            return min(0.08, 1.0 / max(self._fps, 1.0))

    def _run(self) -> None:
        while not self._closed:
            delay = self.tick()
            self._wake.wait(max(0.01, delay))
            self._wake.clear()

    def frame(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def state(self) -> dict[str, object]:
        with self._lock:
            status = dict(self._latest_status)
            current_event = "演示停止" if self._state == "stopped" else ("演示暂停" if self._state == "paused" else "演示播放")
            return {
                "state": self._state,
                "mode": "demo",
                "case_id": None if self._case is None else self._case.case_id,
                "title": None if self._case is None else self._case.title,
                "position_seconds": round(self._position, 3),
                "duration_seconds": None if self._case is None else self._case.duration_seconds,
                "current_event": current_event,
                **status,
            }

    def close(self) -> None:
        self._closed = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        with self._lock:
            self._release_capture()
        self.publisher.close()