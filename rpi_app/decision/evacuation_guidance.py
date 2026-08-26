"""Explainable, non-alarming left/right stair-exit guidance.

This module deliberately does not change the formal visual risk state.  It
only chooses whether a pair of MAX7219 arrow matrices should suggest the less
occupied exit when exactly one side is substantially more crowded.
"""

from __future__ import annotations

from typing import Mapping


def exit_guidance(
    left_people: int,
    right_people: int,
    settings: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return UART-ready exit facts and a safe optional diversion direction.

    A direction is emitted only when one side reaches the configured minimum
    occupancy and exceeds the other side by the configured gap.  If both
    sides are crowded, or neither is, there is no single safe recommendation.
    """
    config = dict(settings or {})
    enabled = bool(config.get("enabled", True))
    minimum_people = max(1, int(config.get("minimum_people", 4)))
    minimum_gap = max(1, int(config.get("minimum_gap", 2)))
    left = max(0, int(left_people))
    right = max(0, int(right_people))

    left_crowded = enabled and left >= minimum_people and left >= right + minimum_gap
    right_crowded = enabled and right >= minimum_people and right >= left + minimum_gap

    if left_crowded:
        direction = "RIGHT"
    elif right_crowded:
        direction = "LEFT"
    else:
        direction = "NONE"

    return {
        "left_exit_count": left,
        "right_exit_count": right,
        "left_exit_risk": "CROWD" if left_crowded else "NORMAL",
        "right_exit_risk": "CROWD" if right_crowded else "NORMAL",
        "recommended_direction": direction,
    }
