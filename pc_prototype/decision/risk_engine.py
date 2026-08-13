"""慧安楼道初版风险规则引擎。"""

from __future__ import annotations

from typing import Literal

RiskLevel = Literal["NORMAL", "WARNING", "CROWD", "DANGER", "FIRE"]


def risk_from_crowd_index(crowd_index: float) -> RiskLevel:
    if crowd_index < 0.3:
        return "NORMAL"
    if crowd_index < 0.6:
        return "WARNING"
    if crowd_index < 0.8:
        return "CROWD"
    return "DANGER"


class RiskEngine:
    def __init__(self, warning_people: int = 8, danger_people: int = 16) -> None:
        self.warning_people = warning_people
        self.danger_people = danger_people

    def evaluate(
        self,
        left_people: int,
        right_people: int,
        occupancy_growth: float = 0.0,
        direction_conflict: bool = False,
        crowd_index: float | None = None,
        smoke: float | None = None,
        temperature: float | None = None,
        smoke_fire_threshold: float = 1.0,
        temperature_fire_threshold: float = 60.0,
    ) -> RiskLevel:
        """按区域占用人数定级；固定双通道同时拥挤时提升一级。"""
        if (smoke is not None and smoke >= smoke_fire_threshold) or (
            temperature is not None and temperature >= temperature_fire_threshold
        ):
            return "FIRE"

        total_people = left_people + right_people
        if crowd_index is None:
            level = "NORMAL" if total_people < self.warning_people else "WARNING"
            if total_people >= self.danger_people:
                level = "DANGER"
            elif direction_conflict and level == "NORMAL":
                level = "WARNING"
        else:
            level = risk_from_crowd_index(max(0.0, min(1.0, crowd_index)))

        if total_people >= self.danger_people:
            return "DANGER"
        if total_people >= self.warning_people and level == "NORMAL":
            return "WARNING"
        return level
