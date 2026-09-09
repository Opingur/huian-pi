"""Authenticated Windows-to-Pi vision input without opening a second UART."""

from __future__ import annotations

import hmac
import json
import math
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping

from communication.esp32 import ESP32Publisher, Esp32Status, build_uart_payload


_RISK_VALUES = frozenset({"NORMAL", "WARNING", "CROWD", "DANGER"})
_DIRECTION_VALUES = frozenset({"LEFT", "RIGHT", "NONE"})
_MAX_REQUEST_BYTES = 16 * 1024


def validate_remote_status(status: object) -> dict[str, object]:
    """Accept a bounded, protocol-v1 status and stamp it with Pi receive time."""
    if not isinstance(status, Mapping):
        raise ValueError("vision status must be a JSON object")
    required = {"vision_risk", "crowd_index", "total_people", "recommended_direction"}
    if not required.issubset(status):
        raise ValueError("vision status is missing required formal fields")
    compact = build_uart_payload(status)
    if compact["vision_risk"] not in _RISK_VALUES:
        raise ValueError("invalid vision_risk")
    if compact["recommended_direction"] not in _DIRECTION_VALUES:
        raise ValueError("invalid recommended_direction")
    if not math.isfinite(float(compact["crowd_index"])) or not 0.0 <= float(compact["crowd_index"]) <= 1.0:
        raise ValueError("crowd_index must be a finite value between 0 and 1")
    for field in ("total_people", "left_exit_count", "right_exit_count", "running_count"):
        value = int(compact[field])
        if not 0 <= value <= 1000:
            raise ValueError(f"{field} must be between 0 and 1000")
    for field in ("vision_fire_confidence", "vision_smoke_confidence"):
        if not math.isfinite(float(compact[field])) or not 0.0 <= float(compact[field]) <= 1.0:
            raise ValueError(f"{field} must be a finite value between 0 and 1")
    compact["timestamp"] = int(time.time())
    return compact


def esp32_status_payload(status: Esp32Status | None) -> dict[str, object] | None:
    """Serialize the latest Pi-owned ESP32 telemetry for the Windows presenter."""
    if status is None:
        return None
    payload: dict[str, object] = {
        "protocol_version": status.protocol_version,
        "message_type": "esp32_status",
        "uptime_ms": status.uptime_ms,
        "mq2_value": status.mq2_value,
        "mq2_warning": status.mq2_warning,
        "temperature_c": status.temperature_c,
        "temperature_valid": status.temperature_valid,
        "temperature_warning": status.temperature_warning,
        "system_state": status.system_state,
        "vision_valid": status.vision_valid,
    }
    payload.update(dict(status.extras))
    return payload

def _normal_status() -> dict[str, object]:
    return {
        "protocol_version": 1, "timestamp": int(time.time()), "vision_risk": "NORMAL",
        "crowd_index": 0.0, "total_people": 0, "left_exit_risk": "NORMAL",
        "right_exit_risk": "NORMAL", "left_exit_count": 0, "right_exit_count": 0,
        "recommended_direction": "NONE", "direction_conflict": False,
        "vision_fire_suspected": False, "fire_confirmed": False, "vision_smoke_suspected": False,
        "vision_fire_confidence": 0.0, "vision_smoke_confidence": 0.0,
        "running_event": False, "running_count": 0,
    }


class SourceArbitratingPublisher:
    """One UART publisher with a short remote-control lease.

    Local Pi analysis keeps running and rendering as usual. During a valid
    Windows lease only the latest remote result reaches ESP32; after expiry,
    local vision resumes hardware control automatically.
    """

    def __init__(self, publisher: ESP32Publisher, *, remote_lease_seconds: float = 4.0, clock: Any = time.monotonic) -> None:
        if remote_lease_seconds <= 0:
            raise ValueError("remote_lease_seconds must be positive")
        self._publisher = publisher
        self._lease_seconds = float(remote_lease_seconds)
        self._clock = clock
        self._lock = threading.RLock()
        self._remote_until = 0.0
        self._last_remote_risk: str | None = None
        self._closed = False

    @property
    def enabled(self) -> bool:
        return self._publisher.enabled

    @property
    def dry_run(self) -> bool:
        return self._publisher.dry_run

    @property
    def remote_active(self) -> bool:
        with self._lock:
            return not self._closed and self._clock() < self._remote_until

    def send_status(self, status: Mapping[str, object], *, source_timestamp: float | None = None) -> bool:
        """Send a local Pi result unless Windows currently owns the short lease."""
        with self._lock:
            if self._closed or self._clock() < self._remote_until:
                return False
            return self._publisher.send_status(status, source_timestamp=source_timestamp)

    def send_remote_status(self, status: Mapping[str, object]) -> bool:
        """Send an already-validated remote result through the one Pi UART."""
        with self._lock:
            if self._closed:
                return False
            now = self._clock()
            remote_risk = str(status.get("vision_risk", "NORMAL"))
            if now >= self._remote_until or remote_risk != self._last_remote_risk:
                # A source hand-off or real risk transition must reach hardware
                # immediately; steady same-risk frames remain UART-rate-limited.
                self._publisher.reset_send_interval()
            self._remote_until = now + self._lease_seconds
            self._last_remote_risk = remote_risk
            return self._publisher.send_status(status, source_timestamp=now)

    def release_remote(self) -> bool:
        """Clear a completed Windows demonstration instead of leaving an old alert active."""
        with self._lock:
            if self._closed:
                return False
            self._remote_until = 0.0
            self._last_remote_risk = "NORMAL"
            self._publisher.reset_send_interval()
            return self._publisher.send_status(_normal_status(), source_timestamp=self._clock())

    def poll_esp32_status(self, *, now: float | None = None) -> Esp32Status | None:
        with self._lock:
            return self._publisher.poll_esp32_status(now=now)

    def esp32_status_is_stale(self, *, now: float | None = None) -> bool:
        with self._lock:
            return self._publisher.esp32_status_is_stale(now=now)

    def reset_send_interval(self) -> None:
        with self._lock:
            self._publisher.reset_send_interval()

    def close(self) -> None:
        """Processor cleanup is a no-op; main owns final UART close."""
        return None

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            self._remote_until = 0.0
            self._publisher.close()


class RemoteVisionServer:
    """Small authenticated HTTP listener owned by the Pi vision process."""

    def __init__(self, publisher: SourceArbitratingPublisher, bridge_key: str, *, host: str = "0.0.0.0", port: int = 8781) -> None:
        if not bridge_key:
            raise ValueError("A non-empty remote vision key is required")
        self.publisher = publisher
        self._bridge_key = bridge_key
        self.host = host
        self.port = int(port)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def _authorized(self, supplied_key: str | None) -> bool:
        return bool(supplied_key) and hmac.compare_digest(self._bridge_key, supplied_key)

    def start(self) -> None:
        if self._server is not None:
            return
        controller = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "HuianRemoteVision/1.0"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _json(self, payload: Mapping[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
                body = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                if self.path not in {"/api/vision", "/api/vision/release"}:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if not controller._authorized(self.headers.get("X-Huian-Bridge-Key")):
                    self.send_error(HTTPStatus.UNAUTHORIZED)
                    return
                if self.path == "/api/vision/release":
                    self._json({"ok": controller.publisher.release_remote(), "remote_active": False})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > _MAX_REQUEST_BYTES:
                        raise ValueError("request body must be 1-16384 bytes")
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    delivered = controller.publisher.send_remote_status(validate_remote_status(payload))
                except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
                    self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)
                    return
                except RuntimeError as error:
                    self._json({"ok": False, "error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self._json({
                    "ok": delivered,
                    "remote_active": controller.publisher.remote_active,
                    "esp32_status": esp32_status_payload(controller.publisher.poll_esp32_status()),
                })

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="huian-remote-vision", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None