"""OpenCV 结果图绘制。"""

from __future__ import annotations

from typing import Mapping
from math import cos, radians, sin

import cv2


RISK_COLORS = {
    "NORMAL": (0, 255, 0),
    "WARNING": (0, 255, 255),
    "CROWD": (0, 165, 255),
    "DANGER": (0, 0, 255),
}


def _score_bar(score: object, width: int = 5) -> str:
    score = max(0.0, min(1.0, float(score)))
    filled = int(round(score * width))
    return "#" * filled + "-" * (width - filled)


def _draw_dashboard_legacy(
    frame,
    detections: list[Mapping[str, object]],
    status: Mapping[str, object],
    conflict_zone: list[list[float]] | None = None,
    motions: Mapping[int, Mapping[str, object]] | None = None,
    display: Mapping[str, object] | None = None,
):
    """绘制固定左右通道占用、风险及指数；不展示真实运动方向。"""
    image = frame.copy()
    height, width = image.shape[:2]
    middle = width // 2
    risk = str(status["vision_risk"])
    color = RISK_COLORS.get(risk, (255, 255, 255))
    motions = motions or {}
    display = display or {}
    show_flow_debug = bool(display.get("show_flow_debug", True))
    show_track_stats = bool(display.get("show_track_stats", True))
    arrow_length = int(display.get("arrow_length_px", 48))
    if conflict_zone and bool(display.get("show_conflict_zone", True)):
        points = [(int(point[0] * width), int(point[1] * height)) for point in conflict_zone]
        for first, second in zip(points, points[1:] + points[:1]):
            cv2.line(image, first, second, (255, 0, 255), 2)
        cv2.putText(image, "Conflict Zone", points[0], cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)


    for detection in detections:
        x1, y1 = int(detection["x1"]), int(detection["y1"])
        x2, y2 = int(detection["x2"]), int(detection["y2"])
        center_x, center_y = (x1 + x2) // 2, (y1 + y2) // 2
        box_color = (255, 0, 0) if center_x < middle else (0, 0, 255)
        cv2.rectangle(image, (x1, y1), (x2, y2), box_color, 2)
        cv2.circle(image, (center_x, center_y), 4, box_color, -1)
        cv2.putText(
            image,
            f"person {float(detection['confidence']):.2f}",
            (x1, max(25, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            box_color,
            2,
        )

    for track_id, motion in motions.items():
        trail = motion.get("trail", [])
        pixels = [(int(x * width), int(y * height)) for _, x, y in trail]
        for first, second in zip(pixels, pixels[1:]):
            cv2.line(image, first, second, (255, 255, 0), 2)
        if pixels and motion.get("motion_state") == "MOVING":
            heading = radians(float(motion["heading_angle"]))
            end = (pixels[-1][0] + int(arrow_length * cos(heading)), pixels[-1][1] + int(arrow_length * sin(heading)))
            end = (max(0, min(width - 1, end[0])), max(0, min(height - 1, end[1])))
            cv2.arrowedLine(image, pixels[-1], end, (0, 255, 255), 2, tipLength=0.3)
            cv2.putText(image, f"ID {track_id}", (pixels[-1][0], max(18, pixels[-1][1] - 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

    if show_flow_debug: cv2.line(image, (middle, 0), (middle, height), (255, 255, 255), 3)
    if show_track_stats: cv2.putText(image, f"Tracked: {status.get('tracked_people', status['total_people'])}", (25, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    if show_track_stats: cv2.putText(image, f"Moving: {status.get('moving_people', 0)}", (25, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(image, f"RISK: {risk}", (25, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.85, color, 2)
    cv2.putText(image, f"Total: {status['total_people']}", (25, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(image, f"Growth: {float(status['occupancy_growth']):+.2f} person/s", (25, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    cv2.putText(image, f"Crowd index: {float(status['crowd_index']):.2f}", (25, 170), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    if show_flow_debug: cv2.putText(image, f"D:{_score_bar(status['density_score'])} G:{_score_bar(status['growth_score'])} C:{_score_bar(status['conflict_score'])}", (25, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    if bool(status.get("prediction_valid", False)):
        prediction_text = (
            f"Forecast: 10s={status.get('predicted_people_10s')} "
            f"20s={status.get('predicted_people_20s')} "
            f"30s={status.get('predicted_people_30s')}"
        )
        danger_eta = status.get("time_to_danger")
        eta_text = "Danger ETA: --" if danger_eta is None else f"Danger ETA: {danger_eta}s"
        cv2.putText(image, prediction_text, (25, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        cv2.putText(image, eta_text, (25, 255), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    else:
        cv2.putText(image, "Forecast: Collecting data...", (25, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
        cv2.putText(image, "Danger ETA: --", (25, 255), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    groups = status.get("incoming_flow_groups", [])
    convergence_eta = status.get("convergence_eta")
    if show_flow_debug: cv2.putText(image, f"Incoming flow groups: {len(groups)}", (25, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    cv2.putText(image, f"Alarm: {status.get('visual_alarm', 'NONE')}", (25, 305), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255) if status.get("visual_alarm") == "RED" else (0, 255, 255), 2)
    if show_flow_debug: cv2.putText(image, f"Convergence ETA: {'--' if convergence_eta is None else str(convergence_eta) + 's'}", (25, 330), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    if show_flow_debug:
        cv2.putText(image, "Fixed region occupancy; not motion direction", (25, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    return image


from ui.dashboard_layout import draw_dashboard as _draw_teacher_dashboard
from ui.mode_display import draw_dashboard as _draw_overlay


def draw_dashboard(
    frame,
    detections,
    status,
    conflict_zone=None,
    motions=None,
    display=None,
    ui_context=None,
):
    """? layout ????? dashboard ??? overlay?"""
    display = display or {}
    layout = str(display.get("layout", "dashboard")).lower()
    if layout == "overlay":
        return _draw_overlay(frame, detections, status, conflict_zone, motions, display)
    if layout != "dashboard":
        raise ValueError("display.layout ??? dashboard ? overlay")
    return _draw_teacher_dashboard(frame, detections, status, conflict_zone, motions, display, ui_context)


