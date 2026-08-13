"""基于时间窗口的人流趋势分析。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True)
class FlowTrend:
    left_people: int
    right_people: int
    total_people: int
    occupancy_growth: float
    direction_conflict: bool


class PeopleFlowAnalyzer:
    """每秒记录一次固定左右通道的占用人数，并保留最近时间窗口。"""

    def __init__(
        self,
        window_seconds: float = 30.0,
        sample_interval_seconds: float = 1.0,
        conflict_people_per_region: int = 4,
        conflict_min_total: int = 10,
    ) -> None:
        self.window_seconds = window_seconds
        self.sample_interval_seconds = sample_interval_seconds
        self.conflict_people_per_region = conflict_people_per_region
        self.conflict_min_total = conflict_min_total
        self.history: deque[tuple[float, int, int]] = deque()
        self._last_snapshot_at: float | None = None

    def update(
        self, left_people: int, right_people: int, now: float | None = None
    ) -> tuple[FlowTrend, bool]:
        """更新当前占用状态；仅每隔一秒保存快照并标记 JSON 输出时机。"""
        timestamp = monotonic() if now is None else now
        snapshot_saved = (
            self._last_snapshot_at is None
            or timestamp - self._last_snapshot_at >= self.sample_interval_seconds
        )
        if snapshot_saved:
            self.history.append((timestamp, left_people, right_people))
            self._last_snapshot_at = timestamp

        cutoff = timestamp - self.window_seconds
        while len(self.history) > 1 and self.history[0][0] < cutoff:
            self.history.popleft()

        oldest_time, oldest_left, oldest_right = self.history[0]
        elapsed = timestamp - oldest_time
        total_people = left_people + right_people
        oldest_total = oldest_left + oldest_right
        occupancy_growth = 0.0 if elapsed <= 0 else round((total_people - oldest_total) / elapsed, 2)

        return FlowTrend(
            left_people=left_people,
            right_people=right_people,
            total_people=total_people,
            occupancy_growth=occupancy_growth,
            direction_conflict=(
                left_people >= self.conflict_people_per_region
                and right_people >= self.conflict_people_per_region
                and total_people >= self.conflict_min_total
            ),
        ), snapshot_saved
