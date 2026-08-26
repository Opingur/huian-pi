"""Windows-to-Pi client; the Pi main process remains the only UART owner."""

from __future__ import annotations

import json
import time
import warnings
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from communication.esp32 import Esp32Status, build_uart_payload, parse_esp32_status_message


class PiBridgePublisher:
    """Publisher-compatible client that lets Windows video analysis use Pi-owned UART."""

    def __init__(
        self,
        endpoint: str,
        bridge_key: str,
        *,
        send_interval_seconds: float = 1.0,
        status_timeout_seconds: float = 3.0,
        request_timeout_seconds: float = 5.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.bridge_key = bridge_key
        self.enabled = True
        self.dry_run = False
        self.send_interval_seconds = float(send_interval_seconds)
        self.status_timeout_seconds = float(status_timeout_seconds)
        self.request_timeout_seconds = float(request_timeout_seconds)
        if not self.endpoint.startswith(("http://", "https://")):
            raise ValueError("Pi bridge endpoint must start with http:// or https://")
        if not self.bridge_key:
            raise ValueError("Pi bridge key is required for hardware control")
        if min(self.send_interval_seconds, self.status_timeout_seconds, self.request_timeout_seconds) <= 0:
            raise ValueError("Pi bridge intervals must be positive")
        # Windows may have a corporate/system proxy; Pi LAN and Tailscale must be direct.
        self._opener = build_opener(ProxyHandler({}))
        self._last_sent_at: float | None = None
        self._latest_esp32_status: Esp32Status | None = None
        self.delivery_attempts = 0
        self.delivery_successes = 0
        self.delivery_failures = 0

    @property
    def latest_esp32_status(self) -> Esp32Status | None:
        return self._latest_esp32_status

    def esp32_status_is_stale(self, *, now: float | None = None) -> bool:
        if self._latest_esp32_status is None:
            return True
        current = time.monotonic() if now is None else float(now)
        return current - self._latest_esp32_status.received_at > self.status_timeout_seconds

    def reset_send_interval(self) -> None:
        self._last_sent_at = None

    def _post(self, payload: Mapping[str, object]) -> bool:
        encoded = json.dumps(build_uart_payload(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.endpoint,
            data=encoded,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(encoded)),
                "X-Huian-Bridge-Key": self.bridge_key,
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.request_timeout_seconds) as response:
                reply = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            warnings.warn(f"Pi bridge delivery failed; will retry: {error}", RuntimeWarning)
            return False
        raw_status = reply.get("esp32_status") if isinstance(reply, dict) else None
        if isinstance(raw_status, dict):
            parsed = parse_esp32_status_message(json.dumps(raw_status, ensure_ascii=False))
            if parsed is not None:
                self._latest_esp32_status = parsed
        return bool(isinstance(reply, dict) and reply.get("ok"))

    def send_status(self, status: Mapping[str, object], *, source_timestamp: float | None = None) -> bool:
        now = time.monotonic() if source_timestamp is None else float(source_timestamp)
        if self._last_sent_at is not None and now - self._last_sent_at < self.send_interval_seconds:
            return False
        self.delivery_attempts += 1
        delivered = self._post(status)
        if delivered:
            self.delivery_successes += 1
            self._last_sent_at = now
        else:
            self.delivery_failures += 1
        return delivered

    def poll_esp32_status(self, *, now: float | None = None) -> Esp32Status | None:
        return self._latest_esp32_status

    def close(self) -> None:
        """Release the remote-control lease; Pi local vision resumes immediately."""
        request = Request(
            self.endpoint + "/release", data=b"{}",
            headers={
                "Content-Type": "application/json", "Content-Length": "2",
                "X-Huian-Bridge-Key": self.bridge_key,
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.request_timeout_seconds):
                return None
        except (HTTPError, URLError, TimeoutError, OSError):
            return None
