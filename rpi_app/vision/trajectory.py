"""连续轨迹、真实画面运动方向与交汇区接近关系。"""

from __future__ import annotations

from collections import deque
from math import atan2, degrees, hypot
from statistics import median
from typing import Mapping


def _point_segment_distance(point, start, end) -> float:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return hypot(px - x1, py - y1)
    ratio = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_squared))
    return hypot(px - (x1 + ratio * dx), py - (y1 + ratio * dy))


def _inside_polygon(point, polygon) -> bool:
    x, y = point
    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[index - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def distance_to_polygon(point, polygon) -> float:
    """返回归一化点到多边形的距离；在区域内时为 0。"""
    if not polygon or _inside_polygon(point, polygon):
        return 0.0
    return min(
        _point_segment_distance(point, polygon[index - 1], vertex)
        for index, vertex in enumerate(polygon)
    )


class TrajectoryAnalyzer:
    """维护约两秒轨迹并输出平滑的画面运动方向。"""

    def __init__(self, config: Mapping[str, object]) -> None:
        self.trajectory_seconds = float(config.get("trajectory_seconds", 2.0))
        self.min_track_age_seconds = float(config.get("min_track_age_seconds", 0.8))
        self.min_motion_distance_norm = float(config.get("min_motion_distance_norm", 0.015))
        self.history: dict[int, deque[tuple[float, float, float]]] = {}

    def update(
        self,
        tracks: list[dict[str, float | int | str]],
        frame_width: int,
        frame_height: int,
        source_timestamp: float,
        conflict_zone: list[list[float]],
    ) -> dict[int, dict[str, object]]:
        """更新轨迹，并返回按 Track ID 索引的运动分析。"""
        seen_ids: set[int] = set()
        result: dict[int, dict[str, object]] = {}
        polygon = [(float(point[0]), float(point[1])) for point in conflict_zone]

        for track in tracks:
            track_id = int(track["track_id"])
            seen_ids.add(track_id)
            point = (
                float(track["anchor_x"]) / max(frame_width, 1),
                float(track["anchor_y"]) / max(frame_height, 1),
            )
            trail = self.history.setdefault(track_id, deque())
            if not trail or source_timestamp > trail[-1][0]:
                trail.append((source_timestamp, point[0], point[1]))
            cutoff = source_timestamp - self.trajectory_seconds
            while len(trail) > 1 and trail[0][0] < cutoff:
                trail.popleft()

            first_time, first_x, first_y = trail[0]
            age = source_timestamp - first_time
            dx, dy = point[0] - first_x, point[1] - first_y
            distance = hypot(dx, dy)
            elapsed = max(age, 0.0)
            state = "UNCERTAIN"
            heading = None
            speed = 0.0
            if age >= self.min_track_age_seconds:
                if distance < self.min_motion_distance_norm:
                    state = "STATIONARY"
                elif elapsed > 0:
                    state = "MOVING"
                    speed = distance / elapsed
                    heading = round((degrees(atan2(dy, dx)) + 360.0) % 360.0, 1)

            earlier_distance = distance_to_polygon((first_x, first_y), polygon)
            current_distance = distance_to_polygon(point, polygon)
            toward = state == "MOVING" and earlier_distance - current_distance >= self.min_motion_distance_norm
            away = state == "MOVING" and current_distance - earlier_distance >= self.min_motion_distance_norm
            eta = None
            if toward and speed > 0:
                eta = current_distance / speed

            result[track_id] = {
                "track_id": track_id,
                "anchor_point": point,
                "trail": list(trail),
                "dx": round(dx, 4),
                "dy": round(dy, 4),
                "speed_norm": round(speed, 4),
                "heading_angle": heading,
                "motion_state": state,
                "toward_conflict_zone": toward,
                "away_from_conflict_zone": away,
                "distance_to_conflict_zone": round(current_distance, 4),
                "convergence_eta": None if eta is None else round(eta, 2),
            }

        stale_before = source_timestamp - self.trajectory_seconds
        for track_id, trail in list(self.history.items()):
            if track_id not in seen_ids and trail and trail[-1][0] < stale_before:
                del self.history[track_id]
        return result


def median_eta(values: list[float]) -> float | None:
    """多人流 ETA 使用中位数，避免单个最快目标主导结果。"""
    return None if not values else round(float(median(values)), 2)
