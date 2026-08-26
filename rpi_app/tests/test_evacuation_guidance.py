from decision.evacuation_guidance import exit_guidance


def test_left_crowding_recommends_the_right_exit():
    result = exit_guidance(6, 1)
    assert result == {
        "left_exit_count": 6,
        "right_exit_count": 1,
        "left_exit_risk": "CROWD",
        "right_exit_risk": "NORMAL",
        "recommended_direction": "RIGHT",
    }


def test_right_crowding_recommends_the_left_exit():
    result = exit_guidance(1, 6)
    assert result["recommended_direction"] == "LEFT"
    assert result["right_exit_risk"] == "CROWD"


def test_balanced_or_low_occupancy_never_guesses_a_direction():
    for counts in ((3, 0), (5, 5), (6, 5)):
        result = exit_guidance(*counts)
        assert result["recommended_direction"] == "NONE"
        assert result["left_exit_risk"] == "NORMAL"
        assert result["right_exit_risk"] == "NORMAL"


def test_guidance_can_be_disabled_without_changing_counts():
    result = exit_guidance(8, 0, {"enabled": False})
    assert result["left_exit_count"] == 8
    assert result["recommended_direction"] == "NONE"
