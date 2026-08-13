"""Dynamic crowd index using only basic Python arithmetic."""


def _clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(maximum, value))


def calculate_crowd_index(
    left_people,
    right_people,
    occupancy_growth,
    direction_conflict,
    config,
    spatial_convergence_score=None,
):
    """Return density, occupancy-growth and spatial-convergence components.

    occupancy growth is the change in fixed-region occupancy, not a person
    passing speed.  The legacy direction flag is used only when no formal
    spatial-convergence score is supplied.
    """
    left_capacity = float(config["left_capacity"])
    right_capacity = float(config["right_capacity"])
    growth_rate_max = float(config["growth_rate_max"])
    total_capacity = left_capacity + right_capacity
    if total_capacity <= 0 or growth_rate_max <= 0:
        raise ValueError("crowd_index capacities and growth_rate_max must be positive")

    density_score = _clamp((left_people + right_people) / total_capacity)
    growth_score = _clamp(max(0.0, float(occupancy_growth)) / growth_rate_max)
    conflict_score = (
        _clamp(float(spatial_convergence_score))
        if spatial_convergence_score is not None
        else (1.0 if direction_conflict and bool(config.get("use_legacy_direction_conflict", False)) else 0.0)
    )
    index = _clamp(
        float(config["weight_density"]) * density_score
        + float(config["weight_growth"]) * growth_score
        + float(config["weight_conflict"]) * conflict_score
    )
    return {
        "index": round(index, 2),
        "density_score": round(density_score, 2),
        "growth_score": round(growth_score, 2),
        "conflict_score": round(conflict_score, 2),
    }
