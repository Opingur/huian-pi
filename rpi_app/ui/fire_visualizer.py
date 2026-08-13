"""Fire-only visual evidence drawing for the existing dashboard video region."""

from __future__ import annotations

import cv2


FIRE_COLOR = (0, 80, 255)


def fire_label(detection, *, stable_fire: bool = False) -> str:
    """Label real visual Fire evidence; non-Fire classes are not displayable."""
    if str(detection.get("class_name", "")).upper() != "FIRE":
        return ""
    if detection.get("temporal_hold"):
        return "FIRE HOLD"
    return "FIRE" if stable_fire else "FIRE CANDIDATE"


def draw_fire_detections(image, detections, *, stable_fire: bool = False) -> None:
    for detection in detections or []:
        if str(detection.get("class_name", "")).upper() != "FIRE":
            continue
        x1, y1, x2, y2 = (int(value) for value in detection.get("bbox", (0, 0, 0, 0)))
        cv2.rectangle(image, (x1, y1), (x2, y2), FIRE_COLOR, 2)
        confidence = float(detection.get("confidence", 0.0))
        cv2.putText(image, f"{fire_label(detection, stable_fire=stable_fire)} {confidence:.2f}", (x1, max(22, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.62, FIRE_COLOR, 2, cv2.LINE_AA)


def fire_status_text(status) -> tuple[str, tuple[int, int, int]]:
    if not status.get("fire_model_enabled", False):
        return "视觉火情：未接入", (180, 180, 180)
    if status.get("vision_fire_suspected"):
        return "视觉火情：已发现火焰", FIRE_COLOR
    if status.get("fire_detected_raw"):
        return "视觉火情：疑似火焰", (0, 210, 255)
    return "视觉火情：未发现", (80, 180, 80)