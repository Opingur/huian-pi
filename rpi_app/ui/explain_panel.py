"""将真实轨迹上下文整理为适合教师端解释的文字。"""

from __future__ import annotations

from typing import Mapping


def select_motion(motions: Mapping[int, Mapping[str, object]], requested_id: object = None):
    if requested_id is not None:
        try:
            selected = motions.get(int(requested_id))
        except (TypeError, ValueError):
            selected = None
        if selected is not None:
            return selected
    moving = [motion for motion in motions.values() if motion.get("motion_state") == "MOVING"]
    return max(moving, key=lambda item: len(item.get("trail", [])), default=None)


def trajectory_lines(motion, frame_width: int, frame_height: int) -> list[str]:
    if motion is None:
        return ["暂无稳定运动目标"]
    trail = list(motion.get("trail", []))
    if len(trail) < 2:
        return [f"目标编号：{motion.get('track_id')}", "轨迹数据不足"]
    lines = [f"目标编号：{motion.get('track_id')}", "最近位置记录："]
    for source_time, x, y in trail[-4:]:
        lines.append(f"{float(source_time):.1f}s  ({int(float(x) * frame_width)}, {int(float(y) * frame_height)})")
    heading = motion.get("heading_angle")
    if heading is None:
        lines.append(f"运动状态：{motion.get('motion_state')}")
    else:
        lines.append(f"运动方向：{float(heading):.1f}°  位移：({motion.get('dx')}, {motion.get('dy')})")
    return lines

class ExplainTargetLock:
    """Keep one explain target until it has been absent longer than the hold time."""
    def __init__(self, hold_seconds=1.0):
        self.hold_seconds, self.track_id, self.missing_since = float(hold_seconds), None, None
    def choose(self, motions, now, requested_id=None):
        try: requested = None if requested_id is None else int(requested_id)
        except (TypeError, ValueError): requested = None
        if requested is not None and requested in motions:
            self.track_id, self.missing_since = requested, None; return requested
        if self.track_id in motions:
            self.missing_since = None; return self.track_id
        if self.track_id is not None:
            self.missing_since = now if self.missing_since is None else self.missing_since
            if now - self.missing_since <= self.hold_seconds: return self.track_id
        candidates = [motion for motion in motions.values() if motion.get("motion_state") == "MOVING"]
        selected = max(candidates, key=lambda item: len(item.get("trail", [])), default=None)
        self.track_id = None if selected is None else int(selected["track_id"]); self.missing_since = None
        return self.track_id

def trajectory_lines(motion, frame_width: int, frame_height: int) -> list[str]:
    if motion is None: return ["暂无稳定运动目标", "等待连续轨迹数据"]
    trail = list(motion.get("trail", []))
    if len(trail) < 2: return [f"目标编号：{motion.get('track_id')}", "轨迹数据不足"]
    now = float(trail[-1][0]); labels = (("2.0秒前", 2.0), ("1.5秒前", 1.5), ("1.0秒前", 1.0), ("0.5秒前", 0.5), ("现在", 0.0))
    samples = [(label, min(trail, key=lambda item: abs(float(item[0]) - (now - seconds)))) for label, seconds in labels]
    point_text = [f"{label}({int(x * frame_width)},{int(y * frame_height)})" for label, (_, x, y) in samples]
    dx, dy = int(float(motion.get("dx", 0.0)) * frame_width), int(float(motion.get("dy", 0.0)) * frame_height)
    horizontal = "右" if dx > 2 else "左" if dx < -2 else "中"; vertical = "下" if dy > 2 else "上" if dy < -2 else ""
    direction = horizontal + vertical if horizontal != "中" or vertical else "不确定"
    state = {"MOVING": "运动中", "STATIONARY": "静止", "UNCERTAIN": "不确定"}.get(str(motion.get("motion_state")), "不确定")
    return [f"目标编号：{motion.get('track_id')}", f"抽样：{point_text[0]}｜{point_text[1]}", f"抽样：{point_text[2]}｜{point_text[3]}", f"抽样：{point_text[4]}", f"位移变化：Δx={dx}，Δy={dy}", f"方向判断：{direction}；状态：{state}"]
