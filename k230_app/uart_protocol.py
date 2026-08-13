"""Versioned newline-delimited JSON protocol from K230 to ESP32."""

try:
    import ujson as json
except ImportError:
    import json


PROTOCOL_VERSION = 1


def encode_status(status):
    """Encode only the K230 visual-state contract; append one line ending."""
    vision_risk = status.get("vision_risk", status.get("risk_level", status.get("crowd_level", "NORMAL")))
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "device": status.get("device", "Huian_Loudao_01"),
        "vision_risk": vision_risk,
        "crowd_index": status.get("crowd_index", 0.0),
        "left_people": status.get("left_people", 0),
        "right_people": status.get("right_people", 0),
        "total_people": status.get("total_people", 0),
        "direction_conflict": bool(status.get("direction_conflict", False)),
        "timestamp": status.get("timestamp", 0),
    }
    return json.dumps(payload) + "\n"


def send_status(uart, status):
    uart.write(encode_status(status))
