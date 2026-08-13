"""OpenCV 画面叠加显示。"""

from __future__ import annotations

from typing import Mapping

import cv2


RISK_COLORS = {
    "NORMAL": (0, 255, 0),
    "WARNING": (0, 255, 255),
    "CROWD": (0, 165, 255),
    "DANGER": (0, 0, 255),
    "FIRE": (0, 0, 255),
}



def score_bar(score, width=5):
    score = max(0.0, min(1.0, float(score)))
    filled = int(round(score * width))
    return "#" * filled + "-" * (width - filled)

def draw_dashboard(frame, detections: list[Mapping[str, object]], status: Mapping[str, object]):
    """在原始摄像头帧上绘制检测框、左右楼梯和风险信息。"""
    height, width = frame.shape[:2]
    middle = width // 2
    risk = str(status["crowd_level"])
    color = RISK_COLORS[risk]

    for detection in detections:
        x1, y1 = int(detection["x1"]), int(detection["y1"])
        x2, y2 = int(detection["x2"]), int(detection["y2"])
        center_x, center_y = (x1 + x2) // 2, (y1 + y2) // 2
        box_color = (255, 0, 0) if center_x < middle else (0, 0, 255)
        cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
        cv2.circle(frame, (center_x, center_y), 4, box_color, -1)
        cv2.putText(frame, f"person {float(detection['confidence']):.2f}", (x1, max(25, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 2)

    cv2.line(frame, (middle, 0), (middle, height), (255, 255, 255), 3)
    cv2.putText(frame, f"LEFT (DOWN): {status['left_people']}", (25, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 0, 0), 2)
    cv2.putText(frame, f"RIGHT (UP): {status['right_people']}", (middle + 25, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2)
    cv2.putText(frame, f"RISK: {risk}", (25, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
    cv2.putText(frame, f"Occupancy change: {float(status['occupancy_growth']):+.2f} people/s", (25, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    cv2.putText(frame, f"Crowd Index: {float(status.get('crowd_index', 0.0)):.2f}", (25, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
    cv2.putText(frame, f"Density:  {score_bar(status.get('density_score', 0.0))}", (25, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    cv2.putText(frame, f"Growth:   {score_bar(status.get('growth_score', 0.0))}", (25, 205), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    cv2.putText(frame, f"Conflict: {score_bar(status.get('conflict_score', 0.0))}", (25, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    if bool(status["direction_conflict"]):
        cv2.putText(frame, "BOTH FIXED PASSAGES OCCUPIED", (25, 255), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    cv2.putText(frame, "Huian Loudao Safety System (Q: quit)", (25, height - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
    return frame
