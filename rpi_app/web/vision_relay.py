"""Authenticated receiver that relays a Windows vision status to Pi-owned UART."""

from __future__ import annotations

import hmac
from typing import Mapping

from rpi_app.communication.esp32 import ESP32Publisher, Esp32Status, build_uart_payload


class VisionRelay:
    """Accept only formal compact fields; Pi remains the sole ESP32 UART owner."""

    def __init__(self, esp32_config: Mapping[str, object], bridge_key: str, publisher: ESP32Publisher | None = None) -> None:
        if not bridge_key:
            raise ValueError("A non-empty vision bridge key is required")
        self._bridge_key = bridge_key
        self.publisher = publisher or ESP32Publisher(esp32_config, legacy_dry_run=False)

    def authorized(self, supplied_key: str | None) -> bool:
        return bool(supplied_key) and hmac.compare_digest(self._bridge_key, supplied_key)

    @staticmethod
    def _status_payload(status: Esp32Status | None) -> dict[str, object] | None:
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

    def relay(self, status: object) -> dict[str, object]:
        if not isinstance(status, dict):
            raise ValueError("vision status must be a JSON object")
        required = {"vision_risk", "crowd_index", "total_people", "recommended_direction"}
        if not required.issubset(status):
            raise ValueError("vision status is missing required formal fields")
        try:
            compact = build_uart_payload(status)
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid vision status: {error}") from error
        if compact["vision_risk"] not in {"NORMAL", "WARNING", "CROWD", "DANGER"}:
            raise ValueError("invalid vision_risk")
        if compact["recommended_direction"] not in {"LEFT", "RIGHT", "NONE"}:
            raise ValueError("invalid recommended_direction")
        try:
            delivered = self.publisher.send_status(compact)
            esp32_status = self.publisher.poll_esp32_status()
            return {"ok": delivered, "esp32_status": self._status_payload(esp32_status)}
        finally:
            # The normal Pi vision service can later resume ownership of this UART.
            self.publisher.close()

    def close(self) -> None:
        self.publisher.close()
