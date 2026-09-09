"""Calibrated dominant-flow control for the MAX7219 direction arrows.

A video frame never determines a physical left/right route by itself.  Each
camera is calibrated once: screen-up and screen-down movement map to the two
real directions on the stair/corridor model.  The arrows then give temporary
priority to a stable dominant flow, which is useful for ordinary corridor,
stair and running footage without pretending that screen-left is an exit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


_ARROW_DIRECTIONS = frozenset({"LEFT", "RIGHT"})


def _direction(value: object, fallback: str) -> str:
    candidate = str(value).strip().upper()
    return candidate if candidate in _ARROW_DIRECTIONS else fallback


@dataclass
class DominantFlowGuidance:
    """Debounce one calibrated, screen-depth dominant-flow direction."""

    settings: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        config = dict(self.settings or {})
        self.enabled = bool(config.get("enabled", True))
        self.mode = str(config.get("mode", "lateral_retreat")).strip().lower()
        self.route_calibrated = bool(config.get("route_calibrated", False))
        self.screen_up_arrow = _direction(config.get("screen_up_arrow", "LEFT"), "LEFT")
        self.screen_down_arrow = _direction(config.get("screen_down_arrow", "RIGHT"), "RIGHT")
        self.minimum_moving_people = max(1, int(config.get("minimum_moving_people", 2)))
        self.running_min_moving_people = max(1, int(config.get("running_min_moving_people", 1)))
        self.dominance_ratio = min(1.0, max(0.5, float(config.get("dominance_ratio", 0.70))))
        self.vertical_axis_dominance = max(1.0, float(config.get("vertical_axis_dominance", 1.25)))
        self.minimum_depth_motion = max(0.0, float(config.get("minimum_depth_motion", 0.015)))
        self.minimum_direction_gap = max(0, int(config.get("minimum_direction_gap", 1)))
        self.activation_hold_seconds = max(0.0, float(config.get("activation_hold_seconds", 0.8)))
        self.release_hold_seconds = max(0.0, float(config.get("release_hold_seconds", 1.2)))
        self.switch_hold_seconds = max(0.0, float(config.get("switch_hold_seconds", 1.5)))
        self.flash_attention = bool(config.get("flash_attention", True))
        self.attention_risks = {
            str(value).strip().upper()
            for value in config.get("attention_risks", ("WARNING", "CROWD"))
        }
        self.active_direction = "NONE"
        self._candidate_direction = "NONE"
        self._candidate_since: float | None = None

    def _candidate(self, motions: Mapping[int, Mapping[str, object]], running_event: bool) -> dict[str, object]:
        up = down = 0
        for motion in motions.values():
            if motion.get("motion_state") != "MOVING":
                continue
            dx, dy = float(motion.get("dx", 0.0)), float(motion.get("dy", 0.0))
            if abs(dy) < self.minimum_depth_motion or abs(dy) < abs(dx) * self.vertical_axis_dominance:
                continue
            if dy < 0:
                up += 1
            else:
                down += 1
        total = up + down
        dominant_count = max(up, down)
        threshold = self.running_min_moving_people if running_event else self.minimum_moving_people
        dominant_ratio = 0.0 if total == 0 else dominant_count / total
        if (total < threshold or dominant_count < threshold or dominant_ratio < self.dominance_ratio
                or abs(up - down) < self.minimum_direction_gap):
            return {
                "direction": "NONE", "screen_direction": "NONE", "depth_moving_people": total,
                "screen_up_people": up, "screen_down_people": down, "dominance_ratio": round(dominant_ratio, 2),
            }
        screen_direction = "SCREEN_UP" if up > down else "SCREEN_DOWN"
        return {
            "direction": self.screen_up_arrow if screen_direction == "SCREEN_UP" else self.screen_down_arrow,
            "screen_direction": screen_direction,
            "depth_moving_people": total,
            "screen_up_people": up,
            "screen_down_people": down,
            "dominance_ratio": round(dominant_ratio, 2),
        }

    def update(
        self,
        left_people: int,
        right_people: int,
        motions: Mapping[int, Mapping[str, object]] | None,
        source_timestamp: float,
        *,
        running_event: bool = False,
        vision_risk: str = "NORMAL",
    ) -> dict[str, object]:
        """Return one directional command only after stable calibrated evidence."""
        left, right = max(0, int(left_people)), max(0, int(right_people))
        if not self.enabled:
            return _off_guidance(left, right, "guidance_disabled")
        if self.mode == "dominant_depth_flow" and not self.route_calibrated:
            # dy is image motion, not a physical route, until a camera/model
            # calibration explicitly maps both directions to real channels.
            return _off_guidance(left, right, "route_not_calibrated")
        if self.mode != "dominant_depth_flow":
            return _legacy_lateral_guidance(left, right, self.settings, motions)

        evidence = self._candidate(motions or {}, running_event)
        candidate = str(evidence["direction"])
        if candidate == self.active_direction:
            self._candidate_direction, self._candidate_since = candidate, None
        elif candidate != self._candidate_direction:
            self._candidate_direction, self._candidate_since = candidate, float(source_timestamp)
            hold = self.release_hold_seconds if candidate == "NONE" else self.switch_hold_seconds if self.active_direction != "NONE" else self.activation_hold_seconds
            if hold == 0.0:
                self.active_direction = candidate
                self._candidate_since = None
        else:
            hold = self.release_hold_seconds if candidate == "NONE" else self.switch_hold_seconds if self.active_direction != "NONE" else self.activation_hold_seconds
            if self._candidate_since is not None and source_timestamp - self._candidate_since >= hold:
                self.active_direction = candidate
                self._candidate_since = None

        attention = bool(running_event) or str(vision_risk).upper() in self.attention_risks
        direction = self.active_direction
        arrow_mode = "OFF" if direction == "NONE" else f"{direction}_{'FLASH' if attention and self.flash_attention else 'ONLY'}"
        return {
            "left_exit_count": left,
            "right_exit_count": right,
            "left_exit_risk": "NORMAL",
            "right_exit_risk": "NORMAL",
            "recommended_direction": direction,
            "arrow_mode": arrow_mode,
            "guidance_mode": "DOMINANT_DEPTH_FLOW",
            "guidance_reason": "dominant_flow_attention" if direction != "NONE" and attention else "dominant_flow" if direction != "NONE" else "insufficient_stable_flow",
            "lateral_guidance_active": False,
            **evidence,
        }


def _off_guidance(left: int, right: int, reason: str) -> dict[str, object]:
    return {
        "left_exit_count": left, "right_exit_count": right,
        "left_exit_risk": "NORMAL", "right_exit_risk": "NORMAL",
        "recommended_direction": "NONE", "arrow_mode": "OFF",
        "guidance_mode": "DOMINANT_DEPTH_FLOW", "guidance_reason": reason,
        "lateral_guidance_active": False, "screen_direction": "NONE",
        "depth_moving_people": 0, "screen_up_people": 0, "screen_down_people": 0,
        "dominance_ratio": 0.0,
    }

def _legacy_lateral_guidance(
    left: int,
    right: int,
    settings: Mapping[str, object] | None,
    motions: Mapping[int, Mapping[str, object]] | None,
) -> dict[str, object]:
    """Retain the previous explicit lateral-only path for old configurations."""
    config = dict(settings or {})
    enabled = bool(config.get("enabled", True))
    minimum_people = max(1, int(config.get("minimum_people", 4)))
    minimum_gap = max(1, int(config.get("minimum_gap", 2)))
    minimum_lateral_people = max(1, int(config.get("minimum_lateral_moving_people", 3)))
    minimum_lateral_ratio = min(1.0, max(0.0, float(config.get("minimum_lateral_ratio", 0.7))))
    horizontal_dominance = max(1.0, float(config.get("horizontal_axis_dominance", 1.25)))
    moving = [motion for motion in (motions or {}).values() if motion.get("motion_state") == "MOVING"]
    lateral = [motion for motion in moving if abs(float(motion.get("dx", 0.0))) >= abs(float(motion.get("dy", 0.0))) * horizontal_dominance]
    lateral_ratio = 0.0 if not moving else len(lateral) / len(moving)
    lateral_evidence = bool(enabled and len(lateral) >= minimum_lateral_people and lateral_ratio >= minimum_lateral_ratio)
    left_crowded = lateral_evidence and left >= minimum_people and left >= right + minimum_gap
    right_crowded = lateral_evidence and right >= minimum_people and right >= left + minimum_gap
    direction = "NONE" if not enabled else "LEFT" if left_crowded else "RIGHT" if right_crowded else "NONE"
    return {
        "left_exit_count": left, "right_exit_count": right,
        "left_exit_risk": "CROWD" if left_crowded else "NORMAL",
        "right_exit_risk": "CROWD" if right_crowded else "NORMAL",
        "recommended_direction": direction,
        "arrow_mode": {"LEFT": "LEFT_ONLY", "RIGHT": "RIGHT_ONLY"}.get(direction, "OFF"),
        "guidance_mode": "LATERAL_RETREAT", "guidance_reason": "lateral_flow_evidence" if direction != "NONE" else "none",
        "lateral_guidance_active": lateral_evidence, "lateral_moving_people": len(lateral),
        "lateral_motion_ratio": round(lateral_ratio, 2),
    }


def exit_guidance(
    left_people: int,
    right_people: int,
    settings: Mapping[str, object] | None = None,
    motions: Mapping[int, Mapping[str, object]] | None = None,
    *,
    running_event: bool = False,
    vision_risk: str = "NORMAL",
) -> dict[str, object]:
    """Stateless compatibility entry point; video use should retain a controller."""
    return DominantFlowGuidance(settings).update(
        left_people, right_people, motions, 0.0,
        running_event=running_event, vision_risk=vision_risk,
    )