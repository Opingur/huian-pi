"""慧安楼道视觉端风险规则。"""

from __future__ import annotations

from typing import Literal

RiskLevel = Literal["NORMAL", "WARNING", "CROWD", "DANGER"]


def risk_from_crowd_index(crowd_index: float) -> RiskLevel:
    if crowd_index < 0.3:
        return "NORMAL"
    if crowd_index < 0.6:
        return "WARNING"
    if crowd_index < 0.8:
        return "CROWD"
    return "CROWD"


class RiskEngine:
    """将动态拥挤指数与人数安全兜底合并为视觉风险。"""

    def __init__(self, warning_people: int = 8, danger_people: int = 16) -> None:
        self.warning_people = int(warning_people)
        self.danger_people = int(danger_people)

    def evaluate(
        self,
        left_people: int,
        right_people: int,
        occupancy_growth: float = 0.0,
        direction_conflict: bool = False,
        crowd_index: float | None = None,
    ) -> RiskLevel:
        """返回风险级别。

        固定双区域高占用已作为 crowd_index 的 conflict_score 参与计算。
        保留人数兜底：8 人起至少 WARNING；legacy 的 danger_people 阈值到达后仍为 CROWD，
        不与火警 DANGER 混用。occupancy_growth 参数仅为接口兼容。
        """
        _ = direction_conflict
        _ = occupancy_growth
        total_people = int(left_people) + int(right_people)
        if crowd_index is None:
            level: RiskLevel = "NORMAL" if total_people < self.warning_people else "WARNING"
        else:
            level = risk_from_crowd_index(max(0.0, min(1.0, crowd_index)))

        if total_people >= self.danger_people:
            return "CROWD"
        if total_people >= self.warning_people and level == "NORMAL":
            return "WARNING"
        return level
