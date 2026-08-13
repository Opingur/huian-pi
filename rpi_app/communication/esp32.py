"""Duplex, lazy UART transport for Raspberry Pi vision and ESP32 runtime status."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
import warnings
from typing import Any, Mapping


UART_FIELDS = (
    "protocol_version",
    "timestamp",
    "vision_risk",
    "crowd_index",
    "total_people",
    "direction_conflict",
    "vision_fire_suspected",
    "vision_smoke_suspected",
    "vision_fire_confidence",
    "vision_smoke_confidence",
)

ESP32_STATUS_FIELDS = (
    "protocol_version",
    "message_type",
    "uptime_ms",
    "mq2_value",
    "mq2_warning",
    "temperature_c",
    "temperature_valid",
    "temperature_warning",
    "system_state",
    "vision_valid",
)

ESP32_SYSTEM_STATES = frozenset({
    "NORMAL",
    "WARNING",
    "DANGER",
    "CROWD_WARNING",
    "CROWD_DANGER",
    "FIRE",
    "COMM_TIMEOUT",
})
_MAX_RX_BUFFER_BYTES = 4096


@dataclass(frozen=True)
class Esp32Status:
    """One validated ESP32 runtime-status message, stamped by Pi receive time."""

    protocol_version: int
    uptime_ms: int
    mq2_value: int
    mq2_warning: bool
    temperature_c: float | None
    temperature_valid: bool
    temperature_warning: bool
    system_state: str
    vision_valid: bool
    received_at: float


def build_uart_payload(status: Mapping[str, object]) -> dict[str, object]:
    """Select only the stable Pi-to-ESP32 protocol-v1 fields."""
    return {
        "protocol_version": int(status.get("protocol_version", 1)),
        "timestamp": int(status.get("timestamp", 0)),
        "vision_risk": str(status.get("vision_risk", "NORMAL")),
        "crowd_index": float(status.get("crowd_index", 0.0)),
        "total_people": int(status.get("total_people", 0)),
        "direction_conflict": bool(status.get("direction_conflict", False)),
        "vision_fire_suspected": bool(status.get("vision_fire_suspected", False)),
        # Protocol-v1 compatibility: formal smoke sensing is MQ-2 on ESP32, never visual Smoke.
        "vision_smoke_suspected": False,
        "vision_fire_confidence": float(status.get("vision_fire_confidence", 0.0)),
        "vision_smoke_confidence": 0.0,
    }


def encode_uart_message(status: Mapping[str, object]) -> bytes:
    """Encode one Pi-to-ESP32 compact newline-delimited JSON message."""
    return (json.dumps(build_uart_payload(status), ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_esp32_status_message(line: str, *, received_at: float | None = None) -> Esp32Status | None:
    """Parse only complete, validated ESP32-to-Pi status messages; bad input is ignored."""
    try:
        payload = json.loads(line)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not set(ESP32_STATUS_FIELDS).issubset(payload):
        return None
    if payload.get("protocol_version") != 1 or payload.get("message_type") != "esp32_status":
        return None
    if not _is_int(payload["uptime_ms"]) or payload["uptime_ms"] < 0:
        return None
    if not _is_int(payload["mq2_value"]):
        return None
    if not isinstance(payload["mq2_warning"], bool):
        return None
    if not isinstance(payload["temperature_valid"], bool) or not isinstance(payload["temperature_warning"], bool):
        return None
    temperature = payload["temperature_c"]
    if payload["temperature_valid"]:
        if not _is_number(temperature):
            return None
        temperature_c: float | None = float(temperature)
    elif temperature is None:
        temperature_c = None
    else:
        return None
    if payload["system_state"] not in ESP32_SYSTEM_STATES or not isinstance(payload["vision_valid"], bool):
        return None
    return Esp32Status(
        protocol_version=1,
        uptime_ms=int(payload["uptime_ms"]),
        mq2_value=int(payload["mq2_value"]),
        mq2_warning=payload["mq2_warning"],
        temperature_c=temperature_c,
        temperature_valid=payload["temperature_valid"],
        temperature_warning=payload["temperature_warning"],
        system_state=payload["system_state"],
        vision_valid=payload["vision_valid"],
        received_at=time.monotonic() if received_at is None else float(received_at),
    )


class ESP32Publisher:
    """One shared Serial2 transport: bounded Pi writes plus non-blocking ESP32 reads."""

    def __init__(
        self,
        config: Mapping[str, object] | None = None,
        *,
        legacy_dry_run: bool = True,
    ) -> None:
        settings = dict(config or {})
        self.enabled = bool(settings.get("enabled", True))
        self.dry_run = bool(settings.get("dry_run", legacy_dry_run))
        self.receive_enabled = bool(settings.get("receive_enabled", True))
        self.port = str(settings.get("port", "")).strip()
        self.baud = int(settings.get("baud", 115200))
        self.send_interval_seconds = float(settings.get("send_interval_seconds", 1.0))
        self.status_timeout_seconds = float(settings.get("status_timeout_seconds", 3.0))
        if self.send_interval_seconds <= 0 or self.status_timeout_seconds <= 0:
            raise ValueError("ESP32 UART intervals must be positive")
        self._serial: Any | None = None
        self._last_sent_at: float | None = None
        self._rx_buffer = bytearray()
        self._latest_esp32_status: Esp32Status | None = None

    @property
    def latest_esp32_status(self) -> Esp32Status | None:
        return self._latest_esp32_status

    def esp32_status_is_stale(self, *, now: float | None = None) -> bool:
        if self._latest_esp32_status is None:
            return True
        current = time.monotonic() if now is None else float(now)
        return current - self._latest_esp32_status.received_at > self.status_timeout_seconds

    def _open(self) -> None:
        if self._serial is not None:
            return
        if not self.port:
            raise RuntimeError("ESP32 serial port is not configured; set esp32.port before dry_run=false.")
        try:
            import serial  # Imported only for enabled, real UART use.
        except ImportError as error:
            raise RuntimeError("pyserial is required when esp32.enabled=true and esp32.dry_run=false.") from error
        try:
            # timeout=0 makes poll_esp32_status drain only bytes already buffered by the kernel.
            self._serial = serial.Serial(self.port, self.baud, timeout=0, write_timeout=1)
        except Exception as error:
            raise RuntimeError(
                f"Unable to open ESP32 serial port {self.port!r} at {self.baud} baud: {error}"
            ) from error

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None
        self._rx_buffer.clear()

    def send_status(self, status: Mapping[str, object], *, source_timestamp: float | None = None) -> bool:
        """Send at most once per configured interval; Pi-to-ESP32 protocol is unchanged."""
        if not self.enabled:
            return False
        now = time.monotonic() if source_timestamp is None else float(source_timestamp)
        if self._last_sent_at is not None and now - self._last_sent_at < self.send_interval_seconds:
            return False
        message = encode_uart_message(status)
        if self.dry_run:
            print(message.decode("utf-8").rstrip("\n"), flush=True)
            self._last_sent_at = now
            return True
        self._open()
        try:
            written = self._serial.write(message)
            self._serial.flush()
            if written != len(message):
                raise OSError(f"short UART write: {written}/{len(message)} bytes")
        except Exception as error:
            warnings.warn(f"ESP32 UART write failed; will retry on the next interval: {error}", RuntimeWarning)
            self.close()
            return False
        self._last_sent_at = now
        return True

    def poll_esp32_status(self, *, now: float | None = None) -> Esp32Status | None:
        """Drain complete ESP32 status lines without waiting; malformed lines never escape."""
        if not self.enabled or self.dry_run or not self.receive_enabled:
            return self._latest_esp32_status
        self._open()
        try:
            available = int(getattr(self._serial, "in_waiting", 0))
            if available > 0:
                self._rx_buffer.extend(self._serial.read(available))
        except Exception as error:
            warnings.warn(f"ESP32 UART read failed; will retry on the next interval: {error}", RuntimeWarning)
            self.close()
            return self._latest_esp32_status
        if len(self._rx_buffer) > _MAX_RX_BUFFER_BYTES:
            self._rx_buffer.clear()
            warnings.warn("Discarded oversized ESP32 UART receive buffer.", RuntimeWarning)
            return self._latest_esp32_status
        received_at = time.monotonic() if now is None else float(now)
        while b"\n" in self._rx_buffer:
            raw_line, _, remainder = self._rx_buffer.partition(b"\n")
            self._rx_buffer = bytearray(remainder)
            try:
                line = raw_line.rstrip(b"\r").decode("utf-8")
            except UnicodeDecodeError:
                continue
            parsed = parse_esp32_status_message(line, received_at=received_at)
            if parsed is not None:
                self._latest_esp32_status = parsed
        return self._latest_esp32_status
