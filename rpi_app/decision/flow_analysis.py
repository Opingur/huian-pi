"""Formal flow-group and spatial-convergence risk analysis.

The analyser consumes the A/B/C assignments produced from real tracked motion.
It never infers a red alarm from heading difference alone: group centroids must
also be closing and predicted to enter the same local area.
"""

from __future__ import annotations

from math import atan2, cos, degrees, hypot, radians, sin
from typing import Mapping


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _angle_gap(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


class FlowRiskAnalyzer:
    """Build formal A/B/C groups and score evidence of spatial convergence."""

    def __init__(self, config: Mapping[str, object] | None = None) -> None:
        values = config or {}
        self.enabled = bool(values.get("enabled", True))
        self.min_group_people = int(values.get("min_group_people", 2))
        self.min_total_people = int(values.get("min_total_people", 6))
        self.min_heading_difference_deg = float(values.get("min_heading_difference_deg", 45.0))
        self.max_current_distance_norm = float(values.get("max_current_distance_norm", 0.42))
        self.max_future_distance_norm = float(values.get("max_future_distance_norm", 0.18))
        self.prediction_horizon_seconds = float(values.get("prediction_horizon_seconds", 2.0))
        self.max_convergence_eta_seconds = float(values.get("max_convergence_eta_seconds", 3.0))
        self.convergence_score_threshold = float(values.get("convergence_score_threshold", 0.65))
        self.min_group_stability = float(values.get("min_group_stability", 0.6))
        self.single_flow_min_people = int(values.get("single_flow_min_people", 6))
        self.prediction_warning_people = int(values.get("prediction_warning_people", 8))
        self.single_flow_min_dominance_ratio = float(values.get("single_flow_min_dominance_ratio", 0.7))

    @staticmethod
    def _motion_velocity(motion: Mapping[str, object]) -> tuple[float, float]:
        speed = float(motion.get("speed_norm", 0.0))
        heading = motion.get("heading_angle")
        if heading is None or speed <= 0:
            return 0.0, 0.0
        angle = radians(float(heading))
        return speed * cos(angle), speed * sin(angle)

    def _formal_groups(self, motions: list[Mapping[str, object]], visual_groups: Mapping[int, Mapping[str, object]]) -> list[dict[str, object]]:
        members_by_label: dict[str, list[Mapping[str, object]]] = {}
        for motion in motions:
            track_id = int(motion.get("track_id", -1))
            assignment = visual_groups.get(track_id)
            if assignment is None or motion.get("motion_state") != "MOVING":
                continue
            label = str(assignment.get("label", ""))
            if label:
                members_by_label.setdefault(label, []).append(motion)
        groups: list[dict[str, object]] = []
        for label in sorted(members_by_label)[:3]:
            members = members_by_label[label]
            count = len(members)
            points = [member.get("anchor_point", (0.0, 0.0)) for member in members]
            velocities = [self._motion_velocity(member) for member in members]
            mean_vx = sum(value[0] for value in velocities) / count
            mean_vy = sum(value[1] for value in velocities) / count
            heading = (degrees(atan2(mean_vy, mean_vx)) + 360.0) % 360.0 if hypot(mean_vx, mean_vy) > 0 else None
            stability = sum(min(1.0, len(member.get("trail", [])) / 3.0) for member in members) / count
            group = {
                "group_id": label, "member_track_ids": sorted(int(member["track_id"]) for member in members), "people_count": count,
                "centroid_x": round(sum(float(point[0]) for point in points) / count, 4), "centroid_y": round(sum(float(point[1]) for point in points) / count, 4),
                "mean_vx": round(mean_vx, 4), "mean_vy": round(mean_vy, 4), "mean_speed": round(hypot(mean_vx, mean_vy), 4),
                "heading_angle": None if heading is None else round(heading, 1), "stability": round(stability, 2),
            }
            group["is_main"] = bool(count >= self.min_group_people and stability >= self.min_group_stability and heading is not None)
            groups.append(group)
        return groups

    def _pair_evidence(self, first: Mapping[str, object], second: Mapping[str, object]) -> dict[str, object]:
        dx = float(second["centroid_x"]) - float(first["centroid_x"]); dy = float(second["centroid_y"]) - float(first["centroid_y"])
        current_distance = hypot(dx, dy)
        relative_vx = float(second["mean_vx"]) - float(first["mean_vx"]); relative_vy = float(second["mean_vy"]) - float(first["mean_vy"])
        relative_speed_squared = relative_vx * relative_vx + relative_vy * relative_vy; closing_dot = dx * relative_vx + dy * relative_vy
        eta = None
        if closing_dot < 0 and relative_speed_squared > 0:
            candidate_eta = -closing_dot / relative_speed_squared
            if candidate_eta <= self.max_convergence_eta_seconds: eta = candidate_eta
        horizon = self.prediction_horizon_seconds; future_dx = dx + relative_vx * horizon; future_dy = dy + relative_vy * horizon; future_distance = hypot(future_dx, future_dy)
        heading_difference = _angle_gap(float(first["heading_angle"]), float(second["heading_angle"])); people_total = int(first["people_count"]) + int(second["people_count"])
        closing_score = _clamp((-closing_dot) / max(current_distance * hypot(relative_vx, relative_vy), 1e-9)); proximity_score = _clamp((self.max_future_distance_norm - future_distance) / self.max_future_distance_norm)
        heading_score = _clamp((heading_difference - self.min_heading_difference_deg) / max(180.0 - self.min_heading_difference_deg, 1e-9)); people_score = _clamp(people_total / max(self.min_total_people, 1))
        score = 0.30 * closing_score + 0.30 * proximity_score + 0.25 * heading_score + 0.15 * people_score
        convergence_point = None
        if eta is not None:
            first_x = float(first["centroid_x"]) + float(first["mean_vx"]) * eta; first_y = float(first["centroid_y"]) + float(first["mean_vy"]) * eta
            second_x = float(second["centroid_x"]) + float(second["mean_vx"]) * eta; second_y = float(second["centroid_y"]) + float(second["mean_vy"]) * eta
            convergence_point = [round((first_x + second_x) / 2, 4), round((first_y + second_y) / 2, 4)]
        spatial_evidence = bool(first["is_main"] and second["is_main"] and people_total >= self.min_total_people and heading_difference >= self.min_heading_difference_deg and current_distance <= self.max_current_distance_norm and closing_dot < 0 and future_distance < current_distance and future_distance <= self.max_future_distance_norm and eta is not None)
        risk = bool(spatial_evidence and score >= self.convergence_score_threshold)
        return {"pair": [str(first["group_id"]), str(second["group_id"])], "current_distance": round(current_distance, 4), "future_distance": round(future_distance, 4), "heading_difference": round(heading_difference, 1), "eta": None if eta is None else round(eta, 2), "point": convergence_point, "score": round(score, 2), "spatial_evidence": spatial_evidence, "risk": risk}

    def analyze(self, motions: list[Mapping[str, object]], prediction: Mapping[str, object], visual_groups: Mapping[int, Mapping[str, object]] | None = None) -> dict[str, object]:
        """Return compact protocol data; trails remain exclusively in ui_context."""
        groups = self._formal_groups(motions, visual_groups or {}); moving_people = sum(int(group["people_count"]) for group in groups)
        dominant_group = max(groups, key=lambda group: int(group["people_count"]), default=None); dominant_people = int(dominant_group["people_count"]) if dominant_group else 0
        dominant_ratio = 0.0 if moving_people == 0 else dominant_people / moving_people
        single_flow_risk = bool(dominant_group and dominant_group["is_main"] and dominant_people >= self.single_flow_min_people and dominant_ratio >= self.single_flow_min_dominance_ratio)
        predicted_people = prediction.get("predicted_people", {})
        predicted_single_flow_warning = bool(prediction.get("prediction_valid") and predicted_people.get(10) is not None and float(predicted_people[10]) >= self.prediction_warning_people and dominant_ratio >= self.single_flow_min_dominance_ratio)
        evidence = [self._pair_evidence(first, second) for index, first in enumerate(groups) for second in groups[index + 1:]] if self.enabled else []
        eligible = [item for item in evidence if item["spatial_evidence"]]
        strongest = max(eligible, key=lambda item: float(item["score"]), default=None); active = next((item for item in eligible if item["risk"]), None); selected = active or strongest
        return {"tracked_people": len(motions), "moving_people": moving_people, "flow_groups": groups, "incoming_flow_groups": [group for group in groups if group["is_main"]], "dominant_flow_group": None if dominant_group is None else {"group_id": dominant_group["group_id"], "people_count": dominant_people, "ratio": round(dominant_ratio, 2)}, "single_flow_crowd_risk": single_flow_risk, "predicted_single_flow_warning": predicted_single_flow_warning, "convergence_risk": bool(active), "convergence_score": 0.0 if selected is None else selected["score"], "convergence_eta": None if selected is None else selected["eta"], "convergence_pair": None if selected is None else selected["pair"], "convergence_point": None if selected is None else selected["point"], "convergence_distance": None if selected is None else selected["current_distance"]}
