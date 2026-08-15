"""The formal Raspberry Pi <-> ESP32 JSON contracts used in class."""
from __future__ import annotations

import json
from typing import Any, Mapping

PI_PAYLOAD_FIELDS = (
    "protocol_version", "timestamp", "vision_risk", "crowd_index", "total_people",
    "direction_conflict", "vision_fire_suspected", "vision_smoke_suspected",
    "vision_fire_confidence", "vision_smoke_confidence",
)
ESP32_STATUS_FIELDS = (
    "protocol_version", "message_type", "uptime_ms", "mq2_value", "mq2_warning",
    "temperature_c", "temperature_valid", "temperature_warning", "system_state", "vision_valid",
)

DEFAULT_PI_PAYLOAD: dict[str, Any] = {
    "protocol_version": 1, "timestamp": 0, "vision_risk": "NORMAL", "crowd_index": 0.0,
    "total_people": 0, "direction_conflict": False, "vision_fire_suspected": False,
    "vision_smoke_suspected": False, "vision_fire_confidence": 0.0,
    "vision_smoke_confidence": 0.0,
}


def build_pi_payload(values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build the exact v1 payload emitted by rpi_app/communication/esp32.py."""
    payload = dict(DEFAULT_PI_PAYLOAD)
    if values:
        for key in PI_PAYLOAD_FIELDS:
            if key in values:
                payload[key] = values[key]
    payload["protocol_version"] = int(payload["protocol_version"])
    payload["timestamp"] = int(payload["timestamp"])
    payload["crowd_index"] = float(payload["crowd_index"])
    payload["total_people"] = int(payload["total_people"])
    payload["direction_conflict"] = bool(payload["direction_conflict"])
    payload["vision_fire_suspected"] = bool(payload["vision_fire_suspected"])
    # Pi protocol v1 currently deliberately keeps visual smoke at false/zero.
    payload["vision_smoke_suspected"] = False
    payload["vision_fire_confidence"] = float(payload["vision_fire_confidence"])
    payload["vision_smoke_confidence"] = 0.0
    return payload


def parse_json_object(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("JSON 顶层必须是对象（{...}）。")
    return value


def format_json_text(text: str) -> str:
    return json.dumps(parse_json_object(text), ensure_ascii=False, indent=2)


def validate_pi_payload(payload: Mapping[str, Any]) -> tuple[bool, str]:
    missing = [field for field in PI_PAYLOAD_FIELDS if field not in payload]
    if missing:
        return False, "缺少正式 Pi 协议字段：" + ", ".join(missing)
    if payload.get("protocol_version") != 1:
        return False, "protocol_version 必须为 1。"
    return True, "Pi 协议字段完整。"


def encode_uart_message(text: str) -> bytes:
    """Validate and encode one compact UTF-8 JSON line, exactly like Pi UART."""
    payload = parse_json_object(text)
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def parse_esp32_status(text: str) -> dict[str, Any] | None:
    """Return only complete esp32_status lines; debug text safely returns None."""
    try:
        payload = parse_json_object(text)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if payload.get("protocol_version") != 1 or payload.get("message_type") != "esp32_status":
        return None
    if not all(field in payload for field in ESP32_STATUS_FIELDS):
        return None
    return payload


CASE_EXPECTED_RESPONSES = {
    "NORMAL": "预期硬件响应：绿灯常亮；蜂鸣器静音。",
    "WARNING": "预期硬件响应：蓝灯常亮；慢速短促蜂鸣。",
    "CROWD": "预期硬件响应：黄灯闪烁；快速、连续、短促蜂鸣。",
    "DANGER": "预期硬件响应：火警——红灯快速闪烁；蜂鸣器持续长鸣。",
}


def classroom_case_expected_response(name: str) -> str:
    return CASE_EXPECTED_RESPONSES.get(name.upper(), "该示例用于协议或 JSON 错误教学，不应预期硬件状态切换。")
def classroom_case(name: str) -> str:
    """Load-only examples; NORMAL/WARNING/CROWD/DANGER are accepted by formal .ino."""
    upper = name.upper()
    if upper == "PROTOCOL_ERROR":
        payload = build_pi_payload({"protocol_version": 99, "vision_risk": "DANGER"})
    elif upper == "INVALID_JSON":
        return '{"protocol_version": 1, "vision_risk": }'
    else:
        risk = upper if upper in {"NORMAL", "WARNING", "CROWD", "DANGER"} else "NORMAL"
        if risk == "DANGER":
            payload = build_pi_payload({
                "vision_risk": "DANGER", "crowd_index": 0.0, "total_people": 0,
                "direction_conflict": False, "vision_fire_suspected": True,
                "vision_fire_confidence": 0.95,
            })
        else:
            people = {"NORMAL": 0, "WARNING": 8, "CROWD": 12}[risk]
            payload = build_pi_payload({
                "vision_risk": risk, "crowd_index": {"NORMAL": 0.0, "WARNING": 0.4, "CROWD": 0.7}[risk],
                "total_people": people, "direction_conflict": risk == "CROWD",
            })
    return json.dumps(payload, ensure_ascii=False, indent=2)
