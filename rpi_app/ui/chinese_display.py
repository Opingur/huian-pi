"""Pillow 中文视频界面绘制。"""

from __future__ import annotations

from functools import lru_cache
from math import cos, radians, sin
from pathlib import Path
from typing import Mapping

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


RISK_ZH = {
    "NORMAL": "正常",
    "WARNING": "注意",
    "CROWD": "拥挤",
    "DANGER": "危险",
}
ALARM_ZH = {
    "NONE": "无",
    "YELLOW": "黄色预警",
    "RED": "红色警报",
}
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)


@lru_cache(maxsize=16)
def _load_font(font_path: str | None, font_size: int) -> ImageFont.FreeTypeFont:
    """优先使用配置字体，否则自动查找 Windows / Raspberry Pi 常见中文字体。"""
    candidates = ((font_path,) if font_path else ()) + _FONT_CANDIDATES
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, font_size)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw_text(image, entries, font_path: str | None, default_size: int):
    """一次 PIL 转换完成一帧中全部文字，避免 OpenCV 中文乱码。"""
    canvas = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    drawer = ImageDraw.Draw(canvas)
    fonts: dict[int, ImageFont.FreeTypeFont] = {}
    for position, text, color, font_size in entries:
        size = font_size or default_size
        font = fonts.setdefault(size, _load_font(font_path, size))
        drawer.text(position, text, font=font, fill=color)
    return cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)


def _people(value: object) -> str:
    return "--" if value is None else f"{float(value):.1f} 人"


def _panel_entries(status: Mapping[str, object]):
    risk = str(status["vision_risk"])
    alarm = str(status.get("visual_alarm", "NONE"))
    risk_color = {
        "NORMAL": (90, 220, 90),
        "WARNING": (255, 220, 0),
        "CROWD": (255, 165, 0),
        "DANGER": (255, 80, 80),
    }.get(risk, (255, 255, 255))
    alarm_color = (255, 80, 80) if alarm == "RED" else (255, 220, 0) if alarm == "YELLOW" else (255, 255, 255)
    entries = [
        ((30, 28), "慧安安全监测系统", (255, 255, 255), 26),
        ((30, 68), f"当前人数：{int(status['total_people'])} 人", (255, 255, 255), 23),
        ((30, 102), f"风险等级：{RISK_ZH.get(risk, risk)}", risk_color, 23),
        ((30, 136), f"拥挤指数：{float(status['crowd_index']):.2f}", (255, 255, 255), 23),
    ]
    if bool(status.get("prediction_valid", False)):
        slope = float(status.get("prediction_slope", 0.0))
        danger_eta = status.get("time_to_danger")
        eta = "预计危险：--" if danger_eta is None else f"预计危险：{float(danger_eta):.1f} 秒"
        entries.extend([
            ((30, 170), f"人数趋势：{slope:+.2f} 人/秒", (255, 255, 255), 23),
            ((30, 208), "短时预测", (255, 255, 255), 23),
            ((45, 242), f"10秒后：{_people(status.get('predicted_people_10s'))}", (255, 255, 255), 21),
            ((45, 274), f"20秒后：{_people(status.get('predicted_people_20s'))}", (255, 255, 255), 21),
            ((45, 306), f"30秒后：{_people(status.get('predicted_people_30s'))}", (255, 255, 255), 21),
            ((30, 342), eta, (255, 255, 255), 23),
            ((30, 376), f"预警状态：{ALARM_ZH.get(alarm, alarm)}", alarm_color, 23),
        ])
        return entries, 410
    entries.extend([
        ((30, 170), "人数趋势：数据采集中", (255, 255, 255), 23),
        ((30, 208), "短时预测：数据采集中...", (255, 255, 255), 23),
        ((30, 246), "预计危险：--", (255, 255, 255), 23),
        ((30, 284), f"预警状态：{ALARM_ZH.get(alarm, alarm)}", alarm_color, 23),
    ])
    return entries, 318


def draw_dashboard(
    frame,
    detections: list[Mapping[str, object]],
    status: Mapping[str, object],
    conflict_zone: list[list[float]] | None = None,
    motions: Mapping[int, Mapping[str, object]] | None = None,
    display: Mapping[str, object] | None = None,
):
    """绘制中文比赛面板；调试模式额外显示中文分析信息。"""
    image = frame.copy()
    height, width = image.shape[:2]
    middle = width // 2
    motions = motions or {}
    display = display or {}
    show_flow_debug = bool(display.get("show_flow_debug", True))
    show_track_stats = bool(display.get("show_track_stats", True))
    arrow_length = int(display.get("arrow_length_px", 48))
    font_path_value = display.get("font_path")
    font_path = str(font_path_value) if font_path_value else None
    font_size = int(display.get("font_size", 24))
    entries, panel_height = _panel_entries(status)

    panel = image.copy()
    cv2.rectangle(panel, (15, 15), (430, panel_height), (20, 20, 20), -1)
    image = cv2.addWeighted(panel, 0.72, image, 0.28, 0)

    if conflict_zone and bool(display.get("show_conflict_zone", True)):
        points = [(int(point[0] * width), int(point[1] * height)) for point in conflict_zone]
        for first, second in zip(points, points[1:] + points[:1]):
            cv2.line(image, first, second, (255, 0, 255), 2)
        entries.append((points[0], "冲突区域", (255, 0, 255), 20))

    for detection in detections:
        x1, y1 = int(detection["x1"]), int(detection["y1"])
        x2, y2 = int(detection["x2"]), int(detection["y2"])
        center_x, center_y = (x1 + x2) // 2, (y1 + y2) // 2
        box_color = (255, 0, 0) if center_x < middle else (0, 0, 255)
        cv2.rectangle(image, (x1, y1), (x2, y2), box_color, 2)
        cv2.circle(image, (center_x, center_y), 4, box_color, -1)
        entries.append(((x1, max(2, y1 - 25)), f"人员 {float(detection['confidence']):.2f}", (255, 255, 255), 18))

    for track_id, motion in motions.items():
        pixels = [(int(x * width), int(y * height)) for _, x, y in motion.get("trail", [])]
        for first, second in zip(pixels, pixels[1:]):
            cv2.line(image, first, second, (255, 255, 0), 2)
        if pixels and motion.get("motion_state") == "MOVING":
            heading = radians(float(motion["heading_angle"]))
            end = (pixels[-1][0] + int(arrow_length * cos(heading)), pixels[-1][1] + int(arrow_length * sin(heading)))
            end = (max(0, min(width - 1, end[0])), max(0, min(height - 1, end[1])))
            cv2.arrowedLine(image, pixels[-1], end, (0, 255, 255), 2, tipLength=0.3)
            entries.append(((pixels[-1][0], max(2, pixels[-1][1] - 25)), f"编号 {track_id}", (0, 255, 255), 18))

    if show_flow_debug:
        cv2.line(image, (middle, 0), (middle, height), (255, 255, 255), 3)
        entries.extend([
            ((25, height - 135), f"左区域：{status.get('left_people', 0)}  右区域：{status.get('right_people', 0)}", (255, 255, 255), 18),
            ((25, height - 108), f"密度：{status.get('density_score', 0):.2f}  增长：{status.get('growth_score', 0):.2f}  冲突：{status.get('conflict_score', 0):.2f}", (255, 255, 255), 18),
            ((25, height - 81), f"流入组：{len(status.get('incoming_flow_groups', []))}", (255, 255, 255), 18),
            ((25, height - 54), f"汇合时间：{'--' if status.get('convergence_eta') is None else str(status.get('convergence_eta')) + '秒'}", (255, 255, 255), 18),
        ])
        if show_track_stats:
            entries.extend([
                ((25, height - 189), f"跟踪人数：{status.get('tracked_people', status['total_people'])}", (255, 255, 255), 18),
                ((25, height - 162), f"运动人数：{status.get('moving_people', 0)}", (255, 255, 255), 18),
            ])
    return _draw_text(image, entries, font_path, font_size)
