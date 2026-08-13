"""Portable dynamic crowd-risk index using only Python basic math."""


def _clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(maximum, value))


def calculate_crowd_index(
    left_people,
    right_people,
    occupancy_growth,
    direction_conflict,
    config,
):
    """Return normalized density, growth and fixed-passage conflict scores.

    The 30-second occupancy window is supplied by PeopleFlowAnalyzer. Only
    positive occupancy change contributes to growth, so falling counts do not
    raise the risk index.
    """
    left_capacity = float(config["left_capacity"])
    right_capacity = float(config["right_capacity"])
    growth_rate_max = float(config["growth_rate_max"])
    total_capacity = left_capacity + right_capacity
    if total_capacity <= 0 or growth_rate_max <= 0:
        raise ValueError("crowd_index capacities and growth_rate_max must be positive")

    density_score = _clamp((left_people + right_people) / total_capacity)
    growth_score = _clamp(max(0.0, float(occupancy_growth)) / growth_rate_max)
    conflict_score = 1.0 if direction_conflict else 0.0
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
