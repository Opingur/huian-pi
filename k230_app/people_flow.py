"""CanMV MicroPython-compatible occupancy trend analysis."""

import time


class PeopleFlowAnalyzer:
    def __init__(self, window_seconds=30, sample_interval_seconds=1,
                 conflict_people_per_region=4, conflict_min_total=10):
        self.window_ms = int(window_seconds * 1000)
        self.sample_interval_ms = int(sample_interval_seconds * 1000)
        self.conflict_people_per_region = conflict_people_per_region
        self.conflict_min_total = conflict_min_total
        self.history = []
        self.last_snapshot_ms = None

    def update(self, left_people, right_people, now_ms=None):
        if now_ms is None:
            now_ms = time.ticks_ms()
        saved = self.last_snapshot_ms is None or time.ticks_diff(now_ms, self.last_snapshot_ms) >= self.sample_interval_ms
        if saved:
            self.history.append((now_ms, left_people, right_people))
            self.last_snapshot_ms = now_ms
        while len(self.history) > 1 and time.ticks_diff(now_ms, self.history[0][0]) > self.window_ms:
            self.history.pop(0)
        old = self.history[0]
        elapsed_ms = time.ticks_diff(now_ms, old[0])
        total_people = left_people + right_people
        growth = 0.0 if elapsed_ms <= 0 else round((total_people - old[1] - old[2]) * 1000 / elapsed_ms, 2)
        conflict = left_people >= self.conflict_people_per_region and right_people >= self.conflict_people_per_region and total_people >= self.conflict_min_total
        return {"left_people": left_people, "right_people": right_people,
                "total_people": total_people, "occupancy_growth": growth,
                "direction_conflict": conflict}, saved
