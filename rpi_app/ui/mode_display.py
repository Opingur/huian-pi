"""配置驱动的中文多模式视频显示层。"""

from __future__ import annotations

from math import cos, radians, sin
from typing import Mapping

import cv2

from ui.chinese_display import ALARM_ZH, RISK_ZH, _draw_text


MODE_DEFAULTS = {
    "prediction": {
        "title": "慧安安全监测系统",
        "show_boxes": True,
        "show_track_id": True,
        "show_trajectory": True,
        "show_direction_arrow": True,
        "show_conflict_zone": False,
    },
    "direction": {
        "title": "慧安安全监测系统",
        "show_boxes": True,
        "show_track_id": True,
        "show_trajectory": True,
        "show_direction_arrow": True,
        "show_conflict_zone": False,
    },
    "convergence": {
        "title": "慧安安全监测系统",
        "show_boxes": True,
        "show_track_id": True,
        "show_trajectory": True,
        "show_direction_arrow": True,
        "show_conflict_zone": True,
    },
    "live": {
        "title": "慧安安全监测系统",
        "show_boxes": True,
        "show_track_id": True,
        "show_trajectory": True,
        "show_direction_arrow": True,
        "show_conflict_zone": False,
    },
}


MODE_DEFAULTS["explain"] = dict(MODE_DEFAULTS["direction"])
MODE_DEFAULTS["validation"] = dict(MODE_DEFAULTS["explain"])

def _options(display: Mapping[str, object] | None) -> dict[str, object]:
    display = display or {}
    mode = str(display.get("mode", "live")).lower()
    if mode not in MODE_DEFAULTS:
        raise ValueError(f"不支持的 display.mode：{mode}；可选值为 {', '.join(MODE_DEFAULTS)}")
    options = dict(MODE_DEFAULTS[mode])
    for key in ("show_boxes", "show_track_id", "show_trajectory", "show_direction_arrow", "show_conflict_zone"):
        if key in display:
            options[key] = bool(display[key])
    options["mode"] = mode
    options["font_path"] = display.get("font_path")
    options["font_size"] = int(display.get("font_size", 24))
    options["arrow_length_px"] = int(display.get("arrow_length_px", 48))
    return options


def _risk_color(risk: str) -> tuple[int, int, int]:
    return {
        "NORMAL": (90, 220, 90),
        "WARNING": (255, 220, 0),
        "CROWD": (255, 165, 0),
        "DANGER": (255, 80, 80),
    }.get(risk, (255, 255, 255))


def _eta_text(value: object) -> str:
    return "--" if value is None else f"{float(value):.1f} 秒"


def _people_text(value: object) -> str:
    return "--" if value is None else f"{float(value):.1f} 人"


def _panel_entries(status: Mapping[str, object], options: Mapping[str, object]):
    mode = str(options["mode"])
    risk = str(status.get("vision_risk", "NORMAL"))
    alarm = str(status.get("visual_alarm", "NONE"))
    white = (255, 255, 255)
    alarm_color = (255, 80, 80) if alarm == "RED" else (255, 220, 0) if alarm == "YELLOW" else white
    entries = [((30, 28), str(options["title"]), white, 26)]

    if mode == "direction":
        entries.extend([
            ((30, 68), f"当前人数：{int(status.get('total_people', 0))} 人", white, 23),
            ((30, 102), f"跟踪人数：{int(status.get('tracked_people', status.get('total_people', 0)))} 人", white, 23),
            ((30, 136), f"运动人数：{int(status.get('moving_people', 0))} 人", white, 23),
            ((30, 170), "运动方向：自动识别", white, 23),
        ])
        return entries, 205

    if mode == "convergence":
        convergence = bool(status.get("convergence_risk", False))
        convergence_label = "高危" if alarm == "RED" else "接近" if convergence else "正常"
        entries.extend([
            ((30, 68), f"当前人数：{int(status.get('total_people', 0))} 人", white, 23),
            ((30, 102), f"运动人数：{int(status.get('moving_people', 0))} 人", white, 23),
            ((30, 136), f"有效流组：{len(status.get('incoming_flow_groups', []))}", white, 23),
            ((30, 170), f"汇合风险：{convergence_label}", (255, 80, 80) if convergence else white, 23),
            ((30, 204), f"汇合预计时间：{_eta_text(status.get('convergence_eta'))}", white, 23),
            ((30, 238), f"预警状态：{ALARM_ZH.get(alarm, alarm)}", alarm_color, 23),
        ])
        return entries, 272

    entries.extend([
        ((30, 68), f"当前人数：{int(status.get('total_people', 0))} 人", white, 23),
        ((30, 102), f"风险等级：{RISK_ZH.get(risk, risk)}", _risk_color(risk), 23),
    ])
    if mode == "live":
        entries.extend([
            ((30, 136), f"跟踪人数：{int(status.get('tracked_people', status.get('total_people', 0)))} 人", white, 23),
            ((30, 170), f"运动人数：{int(status.get('moving_people', 0))} 人", white, 23),
            ((30, 204), f"拥挤指数：{float(status.get('crowd_index', 0.0)):.2f}", white, 23),
            ((30, 238), "人数趋势：数据采集中" if not status.get("prediction_valid") else f"人数趋势：{float(status.get('prediction_slope', 0.0)):+.2f} 人/秒", white, 23),
            ((30, 272), f"预警状态：{ALARM_ZH.get(alarm, alarm)}", alarm_color, 23),
        ])
        return entries, 306

    entries.append(((30, 136), f"拥挤指数：{float(status.get('crowd_index', 0.0)):.2f}", white, 23))
    if not status.get("prediction_valid"):
        entries.extend([
            ((30, 170), "人数趋势：数据采集中", white, 23),
            ((30, 208), "短时预测：数据采集中...", white, 23),
            ((30, 246), "预计危险：--", white, 23),
            ((30, 284), f"预警状态：{ALARM_ZH.get(alarm, alarm)}", alarm_color, 23),
        ])
        return entries, 318
    entries.extend([
        ((30, 170), f"人数趋势：{float(status.get('prediction_slope', 0.0)):+.2f} 人/秒", white, 23),
        ((30, 208), "短时预测", white, 23),
        ((45, 242), f"10秒后：{_people_text(status.get('predicted_people_10s'))}", white, 21),
        ((45, 274), f"20秒后：{_people_text(status.get('predicted_people_20s'))}", white, 21),
        ((45, 306), f"30秒后：{_people_text(status.get('predicted_people_30s'))}", white, 21),
        ((30, 342), f"预计危险：{_eta_text(status.get('time_to_danger'))}", white, 23),
        ((30, 376), f"预警状态：{ALARM_ZH.get(alarm, alarm)}", alarm_color, 23),
    ])
    return entries, 410


def _draw_tracks(image, detections, motions, options, text_entries):
    height, width = image.shape[:2]
    middle = width // 2
    if options["show_boxes"]:
        for detection in detections:
            x1, y1 = int(detection["x1"]), int(detection["y1"])
            x2, y2 = int(detection["x2"]), int(detection["y2"])
            color = (255, 0, 0) if (x1 + x2) // 2 < middle else (0, 0, 255)
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            cv2.circle(image, ((x1 + x2) // 2, (y1 + y2) // 2), 4, color, -1)
            text_entries.append(((x1, max(2, y1 - 25)), f"人员 {float(detection['confidence']):.2f}", (255, 255, 255), 18))
    for track_id, motion in motions.items():
        pixels = [(int(x * width), int(y * height)) for _, x, y in motion.get("trail", [])]
        if options["show_trajectory"]:
            for first, second in zip(pixels, pixels[1:]):
                cv2.line(image, first, second, (255, 255, 0), 2)
        if pixels and motion.get("motion_state") == "MOVING":
            if options["show_direction_arrow"]:
                heading = radians(float(motion["heading_angle"]))
                length = int(options["arrow_length_px"])
                end = (pixels[-1][0] + int(length * cos(heading)), pixels[-1][1] + int(length * sin(heading)))
                end = (max(0, min(width - 1, end[0])), max(0, min(height - 1, end[1])))
                cv2.arrowedLine(image, pixels[-1], end, (0, 255, 255), 2, tipLength=0.3)
            if options["show_track_id"]:
                text_entries.append(((pixels[-1][0], max(2, pixels[-1][1] - 25)), f"编号 {track_id}", (0, 255, 255), 18))


def _draw_conflict_zone(image, conflict_zone, options, text_entries):
    if not conflict_zone or not options["show_conflict_zone"]:
        return
    height, width = image.shape[:2]
    points = [(int(point[0] * width), int(point[1] * height)) for point in conflict_zone]
    for first, second in zip(points, points[1:] + points[:1]):
        cv2.line(image, first, second, (255, 0, 255), 2)
    text_entries.append((points[0], "冲突区域", (255, 0, 255), 20))


def draw_dashboard(frame, detections, status, conflict_zone=None, motions=None, display=None):
    """根据 display.mode 绘制，不影响任何后台算法或 JSON 字段。"""
    options = _options(display)
    image = frame.copy()
    motions = motions or {}
    entries, panel_height = _panel_entries(status, options)
    panel = image.copy()
    cv2.rectangle(panel, (15, 15), (440, panel_height), (20, 20, 20), -1)
    image = cv2.addWeighted(panel, 0.72, image, 0.28, 0)
    _draw_conflict_zone(image, conflict_zone, options, entries)
    _draw_tracks(image, detections, motions, options, entries)
    path = options["font_path"]
    return _draw_text(image, entries, str(path) if path else None, int(options["font_size"]))
