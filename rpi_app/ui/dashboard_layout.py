"""Unified formal dashboard for people-flow, visual fire evidence, and ESP32 sensors."""

from __future__ import annotations

from typing import Mapping

import cv2
import numpy as np

from ui.chinese_display import _draw_text
from ui.explain_panel import select_motion, trajectory_lines
from ui.fire_visualizer import draw_fire_detections
from ui.flow_group_visualizer import build_flow_groups, draw_flow_legend, draw_flow_tracks
from ui.mode_display import _draw_conflict_zone, _options


CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 1024
VIDEO_X = 0
VIDEO_Y = 0
VIDEO_WIDTH = CANVAS_WIDTH
VIDEO_HEIGHT = 740
INFO_Y = 748
INFO_HEIGHT = 192
TREND_X = 8
TREND_WIDTH = 500
FLOW_X = 516
FLOW_WIDTH = 350
SAFETY_X = 874
SAFETY_WIDTH = 398
STATUS_Y = 948
STATUS_HEIGHT = 76

_DARK = (20, 24, 30)
_PANEL = (29, 35, 44)
_PANEL_BORDER = (74, 88, 105)
_TEXT = (238, 243, 250)
_MUTED = (165, 180, 197)
_TITLE_YELLOW = (255, 205, 35)
_BLUE = (55, 150, 255)
_GREEN = (45, 205, 115)
_YELLOW = (255, 210, 60)
_ORANGE = (255, 148, 35)
_RED = (235, 82, 82)
_PURPLE = (192, 92, 224)
_RUNNING_BORDER_ORANGE = (0, 150, 255)
_RUNNING_BORDER_THICKNESS = 6
_RUNNING_BORDER_FLASH_SECONDS = 0.30


def _cover_resize(image, width: int, height: int):
    """Center-crop to fill the monitoring region without distortion or letterboxing."""
    source_height, source_width = image.shape[:2]
    scale = max(width / source_width, height / source_height)
    resized = cv2.resize(image, (round(source_width * scale), round(source_height * scale)), interpolation=cv2.INTER_AREA)
    crop_x = max(0, (resized.shape[1] - width) // 2)
    crop_y = max(0, (resized.shape[0] - height) // 2)
    return resized[crop_y:crop_y + height, crop_x:crop_x + width]


def _panel(canvas, x: int, y: int, width: int, height: int) -> None:
    cv2.rectangle(canvas, (x, y), (x + width, y + height), _PANEL, -1)
    cv2.rectangle(canvas, (x, y), (x + width, y + height), _PANEL_BORDER, 1)


def _value(source: object, name: str, default: object = None) -> object:
    if isinstance(source, Mapping):
        return source.get(name, default)
    marker = object()
    value = getattr(source, name, marker)
    if value is not marker:
        return value
    # ESP32 optional status fields arrive through Esp32Status.extras.
    extras = getattr(source, "extras", None)
    if isinstance(extras, Mapping):
        return extras.get(name, default)
    return default


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _current_candidate(context: Mapping[str, object]) -> bool:
    """A displayed non-hold box is real evidence from the current inference result."""
    for item in context.get("fire_detections", []) or []:
        if not isinstance(item, Mapping) or bool(item.get("temporal_hold")):
            continue
        if str(item.get("class_name", "")).casefold() == "fire":
            return True
    return False


def _has_fire_evidence(status: Mapping[str, object], context: Mapping[str, object]) -> bool:
    # Raw model hits are diagnostic only.  Public fire evidence starts after the
    # tracker has observed a persistent candidate at the same location.
    return bool(status.get("vision_fire_suspected")) or bool(status.get("fire_candidate_visible"))


def _fused_fire(status: Mapping[str, object], context: Mapping[str, object]) -> bool:
    esp32 = context.get("esp32_status")
    return bool(status.get("fire_confirmed", False)) or _value(esp32, "system_state") == "FIRE"


def _fire_stage(status: Mapping[str, object], context: Mapping[str, object]) -> str:
    if _fused_fire(status, context):
        return "fused"
    candidate_visible = bool(status.get("fire_candidate_visible"))
    raw_fire = bool(status.get("fire_detected_raw"))
    # A confirmed visual fire remains a current alert while the next inference
    # is still hitting; after a miss it changes to the shorter "recent" hold.
    if bool(status.get("vision_fire_suspected")) and raw_fire:
        return "stable"
    if bool(status.get("recent_fire_evidence")) and not candidate_visible:
        return "recent"
    if bool(status.get("vision_fire_suspected")):
        return "stable"
    if candidate_visible:
        return "candidate"
    if bool(status.get("recent_fire_evidence")):
        return "recent"
    return "none"

def _summary(status: Mapping[str, object], context: Mapping[str, object] | None = None) -> tuple[str, tuple[int, int, int]]:
    context = context or {}
    stage = _fire_stage(status, context)
    if stage == "fused":
        return "综合状态：火情报警", _RED
    if stage == "stable":
        return "综合状态：视觉火情预警（待多源确认）", _ORANGE
    if stage == "recent":
        return "综合状态：视觉火情预警（持续观察）", _ORANGE
    if stage == "candidate":
        return "综合状态：疑似火情", _YELLOW
    if str(status.get("visual_alarm", "NONE")) == "RED" or str(status.get("vision_risk", "NORMAL")) == "DANGER":
        return "综合状态：拥挤危险", _RED
    if str(status.get("visual_alarm", "NONE")) == "YELLOW" or str(status.get("vision_risk", "NORMAL")) == "CROWD":
        return "综合状态：拥挤报警", _YELLOW
    if str(status.get("vision_risk", "NORMAL")) == "WARNING":
        return "综合状态：拥挤预警", _BLUE
    return "综合状态：正常运行", _GREEN


def _top_fire_text(status: Mapping[str, object], context: Mapping[str, object]) -> tuple[str, tuple[int, int, int]]:
    stage = _fire_stage(status, context)
    if stage == "fused":
        return "视觉火情：确认火情", _RED
    if stage == "stable":
        return "视觉火情：已发现火焰", _ORANGE
    if stage == "recent":
        return "视觉火情：近期发现，持续观察", _ORANGE
    if stage == "candidate":
        return "视觉火情：疑似火焰", _YELLOW
    return "视觉火情：未发现", _GREEN

def _render_video(frame, detections, status, conflict_zone, motions, display, context):
    options = _options(display)
    annotated = frame.copy()
    entries: list = []
    _draw_conflict_zone(annotated, conflict_zone, options, entries)
    groups = context.get("flow_groups") or build_flow_groups(motions or {})
    highlighted = context.get("explain_target_id") if options["mode"] in {"explain", "validation"} else None
    draw_flow_tracks(annotated, detections, motions or {}, options, groups, entries, highlighted)
    draw_fire_detections(
        annotated,
        context.get("fire_detections", []),
        stable_fire=bool(status.get("vision_fire_suspected")),
    )
    draw_flow_legend(annotated, groups, entries)
    font_path = options.get("font_path")
    annotated = _draw_text(annotated, entries, str(font_path) if font_path else None, int(options["font_size"]))
    return _cover_resize(annotated, VIDEO_WIDTH, VIDEO_HEIGHT), options


def _plot_bounds(rect):
    x, y, width, height = rect
    return x + 42, x + width - 14, y + 76, y + height - 30


def _trend_points(history, status):
    samples = list(history or [])
    if not samples:
        return [], []
    now = float(samples[-1][0])
    real = [(float(sample[0]) - now, _int(sample[1]) + _int(sample[2])) for sample in samples if float(sample[0]) >= now - 15.0]
    forecast = [(10.0, status.get("predicted_people_10s")), (20.0, status.get("predicted_people_20s")), (30.0, status.get("predicted_people_30s"))]
    return real, forecast if bool(status.get("prediction_valid")) else []


def _draw_live_trend(canvas, status, context, entries: list) -> None:
    rect = (TREND_X, INFO_Y, TREND_WIDTH, INFO_HEIGHT)
    _panel(canvas, *rect)
    entries.append(((TREND_X + 16, INFO_Y + 14), "\u4eba\u6d41\u8d8b\u52bf\u4e0e\u9884\u6d4b", _TEXT, 19))
    threshold = status.get("danger_people_threshold")
    calibrated = bool(status.get("crowd_calibrated", False)) and isinstance(threshold, int) and not isinstance(threshold, bool) and threshold > 0
    if calibrated:
        entries.append(((TREND_X + 16, INFO_Y + 40), f"\u5b9e\u9a8c\u53c2\u8003\u9608\u503c\uff1a{threshold}", _RED, 13))
        eta = status.get("time_to_danger")
        eta_text = "\u9884\u8ba1\u8fbe\u5230\u5b9e\u9a8c\u53c2\u8003\u9608\u503c\uff1a--" if not isinstance(eta, (int, float)) else f"\u9884\u8ba1\u7ea6 {float(eta):.1f} \u79d2\u8fbe\u5230\u5b9e\u9a8c\u9608\u503c"
        entries.append(((TREND_X + 16, INFO_Y + 58), eta_text, _MUTED, 12))
    else:
        # In exhibition mode, crowd risk is already decided by the live Crowd Index.
        # A future research threshold must not make a live warning look unavailable.
        entries.append(((TREND_X + 16, INFO_Y + 40), "\u5b9e\u65f6\u98ce\u9669\uff1aCrowd Index \u5224\u65ad", _YELLOW, 13))
        current_risk = str(status.get("vision_risk", "NORMAL"))
        if current_risk == "WARNING":
            forecast_text = "\u5f53\u524d\u5df2\u8fdb\u5165\u62e5\u6324\u9884\u8b66"
        elif current_risk == "CROWD":
            forecast_text = "当前已进入拥挤报警"
        elif current_risk == "DANGER":
            forecast_text = "\u5f53\u524d\u5df2\u8fdb\u5165\u9ad8\u98ce\u9669\u72b6\u6001"
        else:
            eta = status.get("time_to_warning")
            forecast_text = (
                "\u9884\u8ba1\u7ea6 %.1f \u79d2\u8fdb\u5165\u62e5\u6324\u9884\u8b66" % float(eta)
                if isinstance(eta, (int, float))
                else "\u4eba\u6d41\u8d8b\u52bf\u6b63\u5728\u5b9e\u65f6\u5206\u6790"
            )
        entries.append(((TREND_X + 16, INFO_Y + 58), forecast_text, _MUTED, 12))
    real, forecast = _trend_points(context.get("prediction_history", []), status)
    left, right, top, bottom = _plot_bounds(rect)
    for index in range(4):
        y = top + (bottom - top) * index // 3
        cv2.line(canvas, (left, y), (right, y), (52, 62, 75), 1)
    cv2.line(canvas, (left, bottom), (right, bottom), _PANEL_BORDER, 1)
    cv2.line(canvas, (left, top), (left, bottom), _PANEL_BORDER, 1)
    if not real or all(people == 0 for _, people in real):
        entries.extend([
            ((TREND_X + 22, INFO_Y + 78), f"\u5f53\u524d\u4eba\u6570\uff1a{_int(status.get('total_people'))} \u4eba", _TEXT, 18),
            ((TREND_X + 22, INFO_Y + 108), "\u8d8b\u52bf\u6a21\u578b\uff1a\u6682\u65e0\u6709\u6548\u4eba\u6d41\u8d8b\u52bf", _MUTED, 15),
            ((TREND_X + 22, INFO_Y + 136), "\u9884\u6d4b\u6570\u636e\uff1a\u91c7\u96c6\u4e2d", _MUTED, 14),
        ])
        return

    values = [people for _, people in real] + [_number(people) for _, people in forecast if people is not None]
    if calibrated:
        values.append(float(threshold))
    low = min(0.0, min(values) - 1.0)
    high = max(values) + 1.0
    if high <= low:
        high = low + 1.0

    def pixel(relative_time: float, people: float):
        x = int(left + (relative_time + 15.0) / 45.0 * (right - left))
        y = int(bottom - (float(people) - low) / (high - low) * (bottom - top))
        return x, y

    if calibrated:
        danger_y = pixel(0.0, threshold)[1]
        cv2.line(canvas, (left, danger_y), (right, danger_y), (70, 70, 230), 1, cv2.LINE_AA)
    real_pixels = [pixel(time_value, people) for time_value, people in real]
    for first, second in zip(real_pixels, real_pixels[1:]):
        cv2.line(canvas, first, second, (255, 178, 75), 2, cv2.LINE_AA)
    for point in real_pixels:
        cv2.circle(canvas, point, 3, (255, 208, 120), -1)
    now_pixel = pixel(0.0, real[-1][1])
    cv2.line(canvas, (now_pixel[0], top), (now_pixel[0], bottom), (70, 220, 110), 2)
    previous = now_pixel
    for relative_time, people in forecast:
        if people is None:
            continue
        target = pixel(relative_time, _number(people))
        cv2.line(canvas, previous, target, (0, 140, 255), 2, cv2.LINE_AA)
        cv2.circle(canvas, target, 4, (0, 140, 255), 1)
        previous = target
    for relative_time, label in ((-15, "-15\u79d2"), (-10, "-10\u79d2"), (-5, "-5\u79d2"), (0, "\u73b0\u5728"), (10, "+10\u79d2"), (20, "+20\u79d2"), (30, "+30\u79d2")):
        entries.append(((pixel(relative_time, low)[0] - 12, bottom + 5), label, _MUTED, 11))



def _crowd_state(status: Mapping[str, object]) -> tuple[str, tuple[int, int, int]]:
    if str(status.get("visual_alarm", "NONE")) == "RED" or str(status.get("vision_risk", "NORMAL")) == "DANGER":
        return "拥挤危险", _RED
    if str(status.get("visual_alarm", "NONE")) == "YELLOW" or str(status.get("vision_risk", "NORMAL")) == "CROWD":
        return "拥挤报警", _YELLOW
    if str(status.get("vision_risk", "NORMAL")) == "WARNING":
        return "拥挤预警", _BLUE
    return "暂无拥挤风险", _GREEN


def _arrow_command(status: Mapping[str, object]) -> tuple[str, tuple[int, int, int]]:
    """Translate the outgoing ESP32 command into a clear dashboard label."""
    command = str(status.get("arrow_mode", "OFF")).strip().upper()
    labels = {
        "LEFT_ONLY": ("左侧常亮", _GREEN),
        "RIGHT_ONLY": ("右侧常亮", _GREEN),
        "LEFT_FLASH": ("左侧闪烁", _ORANGE),
        "RIGHT_FLASH": ("右侧闪烁", _ORANGE),
        "BOTH_STEADY": ("双侧常亮", _GREEN),
        "BOTH_FLASH": ("双侧闪烁", _ORANGE),
    }
    return labels.get(command, ("未触发", _MUTED))
def _draw_flow_card(canvas, status, entries: list) -> None:
    """Show live people-flow metrics and the outgoing arrow command."""
    _panel(canvas, FLOW_X, INFO_Y, FLOW_WIDTH, INFO_HEIGHT)
    entries.append(((FLOW_X + 16, INFO_Y + 14), "\u4eba\u6d41\u76d1\u6d4b", _TEXT, 19))
    crowd_text, crowd_color = _crowd_state(status)
    running_count = _int(status.get("running_count"))
    event_text = "\u68c0\u6d4b\u5230\u8dd1\u52a8" if bool(status.get("running_event")) else "\u6b63\u5e38\u901a\u884c"
    event_color = _RED if running_count else crowd_color
    arrow_text, arrow_color = _arrow_command(status)
    rows = (
        (("\u5f53\u524d\u4eba\u6570", f"{_int(status.get('total_people'))} \u4eba", _BLUE),
         ("\u8ddf\u8e2a\u4eba\u6570", f"{_int(status.get('tracked_people', status.get('total_people')))} \u4eba", _BLUE)),
        (("\u8fd0\u52a8\u4eba\u6570", f"{_int(status.get('moving_people'))} \u4eba", _BLUE),
         ("\u8dd1\u52a8\u4eba\u6570", f"{running_count} \u4eba", _RED if running_count else _GREEN)),
        (("\u62e5\u6324\u6307\u6570", f"{_number(status.get('crowd_index')):.2f}", _TEXT),
         ("\u4eba\u6d41\u72b6\u6001", crowd_text, crowd_color)),
        (("\u5f53\u524d\u4e8b\u4ef6", event_text, event_color), None),
        (("\u7bad\u5934\u6307\u4ee4", arrow_text, arrow_color), None),
    )
    for index, (left, right) in enumerate(rows):
        y = INFO_Y + 48 + index * 31
        if index:
            cv2.line(canvas, (FLOW_X + 14, y - 9), (FLOW_X + FLOW_WIDTH - 14, y - 9), (61, 73, 87), 1)
        for column_x, item in ((FLOW_X + 16, left), (FLOW_X + 184, right)):
            if item is None:
                continue
            label, value, color = item
            entries.append(((column_x, y), label, _MUTED, 13))
            entries.append(((column_x + 72, y), value, color, 14))


def _environment_rows(status: Mapping[str, object], context: Mapping[str, object]) -> list[tuple[str, str, tuple[int, int, int]]]:
    esp32 = context.get("esp32_status")
    stale = bool(context.get("esp32_status_stale", True))
    configured = bool(context.get("esp32_configured", False))
    stage = _fire_stage(status, context)
    fire_value = "\u786e\u8ba4\u706b\u60c5" if stage == "fused" else "\u5df2\u53d1\u73b0" if stage == "stable" else "\u6301\u7eed\u89c2\u5bdf" if stage == "recent" else "\u7591\u4f3c" if stage == "candidate" else "\u672a\u53d1\u73b0"
    fire_color = _RED if stage == "fused" else _ORANGE if stage in {"stable", "recent"} else _YELLOW if stage == "candidate" else _GREEN

    if esp32 is None:
        missing = "\u6682\u672a\u8fde\u63a5" if configured else "\u672a\u63a5\u5165"
        sensor_rows = [("MQ-2\u70df\u96fe", missing, _MUTED), ("\u73af\u5883\u6e29\u5ea6", missing, _MUTED)]
        esp32_text, esp32_color = missing, _MUTED
        multi = "\u706b\u60c5\u786e\u8ba4" if stage == "fused" else "\u6301\u7eed\u786e\u8ba4\u4e2d" if stage in {"stable", "recent", "candidate"} else "\u6b63\u5e38\u76d1\u6d4b"
    elif stale:
        sensor_rows = [("MQ-2\u70df\u96fe", "\u6682\u65e0\u6570\u636e", _MUTED), ("\u73af\u5883\u6e29\u5ea6", "\u6682\u65e0\u6570\u636e", _MUTED)]
        esp32_text, esp32_color = "\u901a\u4fe1\u8d85\u65f6", _MUTED
        multi = "\u706b\u60c5\u786e\u8ba4" if stage == "fused" else "\u6301\u7eed\u786e\u8ba4\u4e2d" if stage in {"stable", "recent", "candidate"} else "\u6b63\u5e38\u76d1\u6d4b"
    else:
        mq2_warning = bool(_value(esp32, "mq2_warning", False))
        mq2_value = _value(esp32, "mq2_value")
        mq2_ready = bool(_value(esp32, "mq2_ready", False))
        mq2_baseline = _value(esp32, "mq2_baseline")
        if not mq2_ready:
            mq2_text = f"当前 {_int(mq2_value)}｜传感器稳定中"
            mq2_color = _YELLOW
        elif mq2_baseline is None:
            mq2_text = f"当前 {_int(mq2_value)}｜等待环境基线"
            mq2_color = _YELLOW
        else:
            mq2_state = "烟雾预警" if mq2_warning else "状态稳定"
            mq2_text = f"当前 {_int(mq2_value)}｜环境基线 {_int(mq2_baseline)}｜{mq2_state}"
            mq2_color = _BLUE if mq2_warning else _GREEN
        if not bool(_value(esp32, "temperature_valid", False)):
            temp_text, temp_color = "\u6570\u636e\u65e0\u6548", _YELLOW
        else:
            temperature = _value(esp32, "temperature_c")
            temp_warning = bool(_value(esp32, "temperature_warning", False))
            temp_state = "\u5f02\u5e38" if temp_warning else "\u6b63\u5e38"
            temp_text = f"{_number(temperature):.1f} \u2103\uff08{temp_state}\uff09"
            temp_color = _RED if temp_warning else _GREEN
        sensor_rows = [("MQ-2\u70df\u96fe", mq2_text, mq2_color), ("\u73af\u5883\u6e29\u5ea6", temp_text, temp_color)]
        system_state = str(_value(esp32, "system_state", "NORMAL"))
        state_text = "\u6b63\u5e38" if system_state == "NORMAL" else system_state
        esp32_text, esp32_color = f"\u5728\u7ebf / {state_text}", _GREEN
        multi = "\u706b\u60c5\u786e\u8ba4" if stage == "fused" else "\u6301\u7eed\u786e\u8ba4\u4e2d" if stage in {"stable", "recent", "candidate"} else "\u6b63\u5e38\u76d1\u6d4b"
    multi_color = _RED if stage == "fused" else _ORANGE if stage in {"stable", "recent"} else _YELLOW if stage == "candidate" else _GREEN if multi == "\u6b63\u5e38\u76d1\u6d4b" else _MUTED
    return [
        ("\u89c6\u89c9\u706b\u7130", fire_value, fire_color),
        *sensor_rows,
        ("ESP32\u72b6\u6001", esp32_text, esp32_color),
        ("\u591a\u6e90\u72b6\u6001", multi, multi_color),
    ]


def _draw_safety_card(canvas, status, context, entries: list) -> None:
    _panel(canvas, SAFETY_X, INFO_Y, SAFETY_WIDTH, INFO_HEIGHT)
    entries.append(((SAFETY_X + 16, INFO_Y + 14), "安全监测", _TEXT, 19))
    for index, (label, value, color) in enumerate(_environment_rows(status, context)):
        y = INFO_Y + 45 + index * 27
        if index:
            cv2.line(canvas, (SAFETY_X + 14, y - 8), (SAFETY_X + SAFETY_WIDTH - 14, y - 8), (61, 73, 87), 1)
        entries.append(((SAFETY_X + 16, y), label, _MUTED, 13))
        entries.append(((SAFETY_X + 118, y), value, color, 14))


def _draw_explain_bottom(canvas, status, display, context, entries: list) -> None:
    """Keep explanatory evidence panels outside the formal live layout."""
    columns = ((8, 410, "轨迹解释"), (434, 410, "风险组成"), (860, 412, "趋势与阈值"))
    motion = select_motion(context.get("motions", {}), context.get("explain_target_id", display.get("explain_track_id")))
    values = [
        trajectory_lines(motion, _int(context.get("frame_width"), 1), _int(context.get("frame_height"), 1)),
        [f"密度：{_number(status.get('density_score')):.2f}", f"增长：{_number(status.get('growth_score')):.2f}", f"空间风险：{_number(status.get('conflict_score')):.2f}", f"Crowd Index：{_number(status.get('crowd_index')):.2f}"],
        [f"趋势斜率：{_number(status.get('prediction_slope')):+.2f} 人/秒", f"10秒预测：{status.get('predicted_people_10s', '暂无')}", f"20秒预测：{status.get('predicted_people_20s', '暂无')}", f"30秒预测：{status.get('predicted_people_30s', '暂无')}"],
    ]
    for (x, width, title), lines in zip(columns, values):
        _panel(canvas, x, INFO_Y, width, INFO_HEIGHT)
        entries.append(((x + 18, INFO_Y + 16), title, _TEXT, 18))
        for index, line in enumerate(lines[:5]):
            entries.append(((x + 18, INFO_Y + 52 + index * 27), line, _MUTED, 14))


def _running_border_visible(status: Mapping[str, object]) -> bool:
    """Use source time so the running alert flashes consistently on Pi and Windows."""
    if not bool(status.get("running_event", False)):
        return False
    try:
        source_time = float(status.get("source_time", 0.0))
    except (TypeError, ValueError):
        return True
    return int(source_time / _RUNNING_BORDER_FLASH_SECONDS) % 2 == 0


def _draw_running_border(canvas, status: Mapping[str, object]) -> None:
    if not _running_border_visible(status):
        return
    cv2.rectangle(
        canvas,
        (3, 3),
        (CANVAS_WIDTH - 4, CANVAS_HEIGHT - 4),
        _RUNNING_BORDER_ORANGE,
        _RUNNING_BORDER_THICKNESS,
        cv2.LINE_AA,
    )

def draw_dashboard(frame, detections, status, conflict_zone=None, motions=None, display=None, ui_context=None):
    """Render the stable unified dashboard; input names never select a UI branch."""
    display = display or {}
    context = ui_context or {}
    video, options = _render_video(frame, detections, status, conflict_zone, motions, display, context)
    canvas = np.full((CANVAS_HEIGHT, CANVAS_WIDTH, 3), _DARK, dtype=np.uint8)
    canvas[VIDEO_Y:VIDEO_Y + VIDEO_HEIGHT, VIDEO_X:VIDEO_X + VIDEO_WIDTH] = video
    fire_text, fire_color = _top_fire_text(status, context)
    # Restored lightweight overlay: no large header panel obscures the real monitoring image.
    entries: list = [
        ((25, 20), "慧眼疏流安全检测系统", (0, 0, 0), 30),
        ((23, 18), "慧眼疏流安全检测系统", _TITLE_YELLOW, 30),
        ((25, 61), fire_text, (0, 0, 0), 21),
        ((23, 59), fire_text, fire_color, 21),
    ]
    if str(options["mode"]) in {"explain", "validation"}:
        _draw_explain_bottom(canvas, status, display, context, entries)
    else:
        _draw_live_trend(canvas, status, context, entries)
        _draw_flow_card(canvas, status, entries)
        _draw_safety_card(canvas, status, context, entries)
    summary_text, summary_color = _summary(status, context)
    cv2.rectangle(canvas, (0, STATUS_Y), (CANVAS_WIDTH, CANVAS_HEIGHT), (8, 84, 185), -1)
    cv2.circle(canvas, (34, STATUS_Y + STATUS_HEIGHT // 2), 10, summary_color, -1)
    entries.append(((56, STATUS_Y + 12), summary_text, _TEXT, 21))
    _draw_running_border(canvas, status)
    font_path = options.get("font_path")
    return _draw_text(canvas, entries, str(font_path) if font_path else None, int(options["font_size"]))