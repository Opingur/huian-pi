"""Lightweight visual flow grouping for the dashboard."""

from __future__ import annotations

from math import cos, radians, sin
from typing import Mapping

import cv2


FLOW_GROUPS = (
    ("A", (255, 150, 45)),
    ("B", (45, 150, 255)),
    ("C", (200, 90, 190)),
)
WEAK_COLOR = (175, 175, 175)


def _angle_distance(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def build_flow_groups(motions: Mapping[int, Mapping[str, object]]) -> dict[int, dict[str, object]]:
    """Assign at most three groups using moving target heading and proximity."""
    candidates = [
        motion for motion in motions.values()
        if motion.get("motion_state") == "MOVING" and motion.get("heading_angle") is not None
    ]
    candidates.sort(key=lambda item: int(item.get("track_id", 0)))
    groups: list[dict[str, object]] = []
    assigned: dict[int, dict[str, object]] = {}
    for motion in candidates:
        point = motion.get("anchor_point", (0.0, 0.0))
        heading = float(motion["heading_angle"])
        best = None
        best_distance = None
        for group in groups:
            if _angle_distance(heading, float(group["heading"])) > 45.0:
                continue
            center_x, center_y = group["center"]
            distance = ((float(point[0]) - center_x) ** 2 + (float(point[1]) - center_y) ** 2) ** 0.5
            if distance <= 0.28 and (best_distance is None or distance < best_distance):
                best, best_distance = group, distance
        if best is None and len(groups) < len(FLOW_GROUPS):
            label, color = FLOW_GROUPS[len(groups)]
            best = {"label": label, "color": color, "heading": heading, "center": (float(point[0]), float(point[1])), "members": []}
            groups.append(best)
        if best is None:
            continue
        members = best["members"]
        members.append(motion)
        count = len(members)
        old_x, old_y = best["center"]
        best["center"] = ((old_x * (count - 1) + float(point[0])) / count, (old_y * (count - 1) + float(point[1])) / count)
        best["heading"] = heading
        assigned[int(motion["track_id"])] = {"label": best["label"], "color": best["color"]}
    return assigned


def draw_flow_tracks(image, detections, motions, options, flow_groups, text_entries, highlighted_id=None) -> None:
    """Draw one coherent group-color layer; non-grouped targets remain subdued."""
    height, width = image.shape[:2]
    explain = options.get("mode") == "explain"
    for detection in detections:
        track_id = int(detection.get("track_id", -1))
        group = flow_groups.get(track_id, {})
        is_highlighted = highlighted_id is not None and track_id == int(highlighted_id)
        color = tuple(group.get("color", WEAK_COLOR))
        if explain and not is_highlighted:
            color = WEAK_COLOR
        x1, y1 = int(detection["x1"]), int(detection["y1"])
        x2, y2 = int(detection["x2"]), int(detection["y2"])
        if options.get("show_boxes", True):
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 4 if is_highlighted else 2)
        if options.get("show_track_id", True):
            label = f"{group.get('label', '·')}-{track_id}" if group else f"编号 {track_id}"
            text_entries.append(((x1, max(2, y1 - 24)), label, color, 18))
    for track_id, motion in motions.items():
        pixels = [(int(x * width), int(y * height)) for _, x, y in motion.get("trail", [])]
        group = flow_groups.get(int(track_id), {})
        is_highlighted = highlighted_id is not None and int(track_id) == int(highlighted_id)
        color = tuple(group.get("color", WEAK_COLOR))
        if explain and not is_highlighted:
            color = WEAK_COLOR
        if options.get("show_trajectory", True) and len(pixels) > 1:
            cv2.polylines(image, [__import__("numpy").array(pixels)], False, color, 4 if is_highlighted else 2)
        if pixels and motion.get("motion_state") == "MOVING" and options.get("show_direction_arrow", True):
            heading = radians(float(motion["heading_angle"]))
            length = int(options.get("arrow_length_px", 48))
            end = (pixels[-1][0] + int(length * cos(heading)), pixels[-1][1] + int(length * sin(heading)))
            end = (max(0, min(width - 1, end[0])), max(0, min(height - 1, end[1])))
            cv2.arrowedLine(image, pixels[-1], end, color, 3 if is_highlighted else 2, tipLength=0.3)

import numpy as np


def _soften_color(color, strength):
    return tuple(int(WEAK_COLOR[index] + (int(channel) - WEAK_COLOR[index]) * strength) for index, channel in enumerate(color))


def _visual_style(group, explain, is_highlighted, highlighted_group):
    base = tuple(group.get("color", WEAK_COLOR))
    if not explain:
        return base, 2
    if is_highlighted:
        return base, 4
    if group and group.get("label") == highlighted_group:
        return _soften_color(base, 0.65), 2
    return _soften_color(base, 0.40) if group else WEAK_COLOR, 1


def draw_flow_tracks(image, detections, motions, options, flow_groups, text_entries, highlighted_id=None) -> None:
    """Render real track data with explain-mode visual hierarchy only."""
    height, width = image.shape[:2]
    explain = options.get("mode") == "explain"
    highlighted_group = flow_groups.get(int(highlighted_id), {}).get("label") if highlighted_id is not None else None
    for detection in detections:
        track_id = int(detection.get("track_id", -1))
        group = flow_groups.get(track_id, {})
        is_highlighted = highlighted_id is not None and track_id == int(highlighted_id)
        color, thickness = _visual_style(group, explain, is_highlighted, highlighted_group)
        x1, y1, x2, y2 = (int(detection[key]) for key in ("x1", "y1", "x2", "y2"))
        if options.get("show_boxes", True):
            cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness)
        if options.get("show_track_id", True):
            label = f"{group['label']}-{track_id}" if group else f"编号 {track_id}"
            text_entries.append(((x1, max(2, y1 - 24)), label, color, 18 if is_highlighted else 15))
    for track_id, motion in motions.items():
        group = flow_groups.get(int(track_id), {})
        is_highlighted = highlighted_id is not None and int(track_id) == int(highlighted_id)
        color, thickness = _visual_style(group, explain, is_highlighted, highlighted_group)
        pixels = [(int(x * width), int(y * height)) for _, x, y in motion.get("trail", [])]
        if options.get("show_trajectory", True) and len(pixels) > 1:
            cv2.polylines(image, [np.array(pixels)], False, color, thickness)
        if pixels and motion.get("motion_state") == "MOVING" and options.get("show_direction_arrow", True):
            heading = radians(float(motion["heading_angle"]))
            length = int(options.get("arrow_length_px", 48))
            end = (pixels[-1][0] + int(length * cos(heading)), pixels[-1][1] + int(length * sin(heading)))
            end = (max(0, min(width - 1, end[0])), max(0, min(height - 1, end[1])))
            cv2.arrowedLine(image, pixels[-1], end, color, max(1, thickness), tipLength=0.3)


def draw_flow_legend(image, flow_groups, text_entries) -> None:
    """Show only labels for groups that exist in this frame."""
    active = {str(group["label"]): tuple(group["color"]) for group in flow_groups.values() if group.get("label") and group.get("color")}
    if not active:
        return
    x, y = image.shape[1] - 134, 16
    for index, label in enumerate(sorted(active)):
        position = (x, y + index * 34)
        cv2.circle(image, (position[0] + 9, position[1] + 10), 7, active[label], -1)
        try:
            display_label = f"{chr(ord('A') + int(label))}流"
        except (TypeError, ValueError):
            display_label = f"{label}流"
        text_entries.append(((position[0] + 23, position[1]), display_label, active[label], 21))
