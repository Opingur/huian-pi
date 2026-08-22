"""Atomic file bridge from the formal Pi pipeline to the teacher HTTP service."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def runtime_directory() -> Path:
    return PROJECT_ROOT / "output" / "runtime"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return str(value)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


class RuntimeSnapshotPublisher:
    """Publish the already-rendered formal dashboard at a bounded cadence."""

    def __init__(self, directory: Path | None = None, *, enabled: bool = True, interval_seconds: float = 0.25) -> None:
        self.directory = (directory or runtime_directory()).resolve()
        self.enabled = bool(enabled)
        self.interval_seconds = max(0.05, float(interval_seconds))
        self._last_published_at: float | None = None

    @classmethod
    def from_config(cls, settings: Mapping[str, object] | None) -> "RuntimeSnapshotPublisher":
        config = dict(settings or {})
        return cls(
            enabled=bool(config.get("enabled", False)),
            interval_seconds=float(config.get("interval_seconds", 0.25)),
        )

    def publish(self, status: Mapping[str, object], dashboard_bgr, *, source_time: float) -> bool:
        if not self.enabled:
            return False
        now = time.monotonic()
        if self._last_published_at is not None and now - self._last_published_at < self.interval_seconds:
            return False
        success, encoded = cv2.imencode(".jpg", dashboard_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not success:
            return False
        payload = _json_safe(dict(status))
        payload.update({"source_time": round(float(source_time), 3), "published_at_monotonic": round(now, 3)})
        _atomic_write(self.directory / "latest_dashboard.jpg", encoded.tobytes())
        _atomic_write(
            self.directory / "latest_status.json",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        )
        self._last_published_at = now
        return True


def load_latest_status(directory: Path | None = None) -> dict[str, object] | None:
    path = (directory or runtime_directory()) / "latest_status.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def load_latest_frame(directory: Path | None = None) -> bytes | None:
    try:
        return ((directory or runtime_directory()) / "latest_dashboard.jpg").read_bytes()
    except OSError:
        return None