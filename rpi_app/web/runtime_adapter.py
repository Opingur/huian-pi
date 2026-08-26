"""Normalize the formal runtime snapshot for the read-only Pi Web API."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Mapping

from rpi_app.services.runtime_snapshot import load_latest_status


ESP32_FIELDS = (
    "mq2_value", "mq2_phase", "mq2_ready", "mq2_warmup_remaining_ms",
    "mq2_calibration_remaining_ms", "mq2_baseline", "mq2_trigger_threshold",
    "mq2_release_threshold", "mq2_warning", "temperature_c", "temperature_valid",
    "temperature_warning", "humidity_percent", "manual_alarm",
    "manual_alarm_remaining_ms", "manual_alarm_source", "esp32_system_state",
    "recommended_direction",
)


class RuntimeStatusAdapter:
    """Expose only the status already published by the formal vision process."""

    def __init__(self, runtime_directory: Path | None = None, *, max_age_seconds: float = 3.0) -> None:
        self.runtime_directory = runtime_directory
        self.max_age_seconds = max(0.5, float(max_age_seconds))

    def status(self) -> dict[str, object]:
        snapshot = load_latest_status(self.runtime_directory)
        if snapshot is None:
            return self._waiting_status()
        published_at = snapshot.get("published_at_monotonic")
        if not isinstance(published_at, (int, float)):
            return self._waiting_status()
        age_seconds = max(0.0, time.monotonic() - float(published_at))
        if age_seconds > self.max_age_seconds:
            return self._waiting_status(mode="stale", snapshot_age_ms=round(age_seconds * 1000.0, 1))
        status = self._snapshot_status(snapshot)
        status["snapshot_age_ms"] = round(age_seconds * 1000.0, 1)
        return status

    @staticmethod
    def _waiting_status(*, mode: str = "waiting", snapshot_age_ms: float | None = None) -> dict[str, object]:
        status: dict[str, object] = {
            "mode": mode,
            "snapshot_available": False,
            "camera_online": False if mode == "stale" else None,
            "total_people": None,
            "vision_risk": None,
            "crowd_index": None,
            "running_event": None,
            "running_count": None,
            "current_event": None,
            "source_time": None,
            "esp32_online": None,
            "system_state": None,
        }
        status.update({field: None for field in ESP32_FIELDS})
        status["snapshot_age_ms"] = snapshot_age_ms
        return status

    @staticmethod
    def _snapshot_status(snapshot: Mapping[str, object]) -> dict[str, object]:
        status: dict[str, object] = {
            "mode": snapshot.get("mode", "live"),
            "snapshot_available": True,
            "camera_online": snapshot.get("camera_online"),
            "total_people": snapshot.get("total_people"),
            "vision_risk": snapshot.get("vision_risk"),
            "crowd_index": snapshot.get("crowd_index"),
            "running_event": snapshot.get("running_event"),
            "running_count": snapshot.get("running_count"),
            "current_event": snapshot.get("current_event"),
            "source_time": snapshot.get("source_time"),
            "esp32_online": snapshot.get("esp32_online"),
            # There is no separately calculated overall Web risk.  Preserve the
            # actual ESP32 state when it is available instead of inventing one.
            "system_state": snapshot.get("esp32_system_state"),
        }
        for field in ESP32_FIELDS:
            status[field] = snapshot.get(field)
        return status