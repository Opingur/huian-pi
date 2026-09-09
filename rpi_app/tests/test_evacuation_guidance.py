from decision.evacuation_guidance import DominantFlowGuidance, exit_guidance


def _lateral_motion(track_id: int, dx: float = 0.12, dy: float = 0.01):
    return {track_id: {"track_id": track_id, "motion_state": "MOVING", "dx": dx, "dy": dy}}


def _depth_motion(track_id: int, dy: float):
    return {track_id: {"track_id": track_id, "motion_state": "MOVING", "dx": 0.01, "dy": dy}}


def _motions(*motions):
    return {track_id: motion for item in motions for track_id, motion in item.items()}


def _controller(**overrides):
    settings = {
        "enabled": True, "mode": "dominant_depth_flow", "route_calibrated": True,
        "screen_up_arrow": "RIGHT", "screen_down_arrow": "LEFT",
        "minimum_moving_people": 3, "running_min_moving_people": 1,
        "dominance_ratio": 0.7, "vertical_axis_dominance": 1.25,
        "minimum_depth_motion": 0.015, "minimum_direction_gap": 2,
        "activation_hold_seconds": 1.0, "release_hold_seconds": 1.0, "switch_hold_seconds": 1.5,
    }
    settings.update(overrides)
    return DominantFlowGuidance(settings)


def test_legacy_lateral_mode_remains_available_for_old_configurations():
    result = exit_guidance(6, 1, motions=_motions(_lateral_motion(1), _lateral_motion(2), _lateral_motion(3)))
    assert result["recommended_direction"] == "LEFT"
    assert result["left_exit_risk"] == "CROWD"


def test_depth_majority_maps_screen_up_to_the_calibrated_arrow_after_hold():
    guidance = _controller()
    motions = _motions(_depth_motion(1, -0.08), _depth_motion(2, -0.10), _depth_motion(3, -0.12), _lateral_motion(4))
    assert guidance.update(2, 2, motions, 0.0)["arrow_mode"] == "OFF"
    result = guidance.update(2, 2, motions, 1.0)
    assert result["recommended_direction"] == "RIGHT"
    assert result["arrow_mode"] == "RIGHT_ONLY"
    assert result["screen_direction"] == "SCREEN_UP"


def test_attention_flashes_the_confirmed_toward_camera_left_arrow_not_both_arrows():
    guidance = _controller(activation_hold_seconds=0.0)
    motions = _motions(_depth_motion(1, 0.08), _depth_motion(2, 0.10), _depth_motion(3, 0.12))
    result = guidance.update(1, 2, motions, 0.0, vision_risk="WARNING")
    assert result["recommended_direction"] == "LEFT"
    assert result["arrow_mode"] == "LEFT_FLASH"


def test_balanced_or_horizontal_motion_never_selects_a_direction():
    guidance = _controller(activation_hold_seconds=0.0)
    balanced = _motions(_depth_motion(1, -0.08), _depth_motion(2, -0.09), _depth_motion(3, 0.08), _depth_motion(4, 0.09))
    horizontal = _motions(_lateral_motion(1), _lateral_motion(2), _lateral_motion(3))
    assert guidance.update(3, 1, balanced, 0.0)["arrow_mode"] == "OFF"
    assert guidance.update(3, 1, horizontal, 1.0)["arrow_mode"] == "OFF"


def test_direction_switch_and_release_are_debounced():
    guidance = _controller(activation_hold_seconds=0.0, release_hold_seconds=1.0, switch_hold_seconds=1.0)
    up = _motions(_depth_motion(1, -0.08), _depth_motion(2, -0.10), _depth_motion(3, -0.12))
    down = _motions(_depth_motion(1, 0.08), _depth_motion(2, 0.10), _depth_motion(3, 0.12))
    assert guidance.update(1, 1, up, 0.0)["recommended_direction"] == "RIGHT"
    assert guidance.update(1, 1, down, 0.5)["recommended_direction"] == "RIGHT"
    assert guidance.update(1, 1, down, 1.5)["recommended_direction"] == "LEFT"
    assert guidance.update(1, 1, {}, 2.0)["recommended_direction"] == "LEFT"
    assert guidance.update(1, 1, {}, 3.0)["arrow_mode"] == "OFF"

def test_uncalibrated_depth_motion_never_controls_a_physical_arrow():
    guidance = DominantFlowGuidance({"enabled": True, "mode": "dominant_depth_flow"})
    motions = _motions(_depth_motion(1, -0.08), _depth_motion(2, -0.10), _depth_motion(3, -0.12))
    result = guidance.update(1, 1, motions, 2.0)
    assert result["arrow_mode"] == "OFF"
    assert result["guidance_reason"] == "route_not_calibrated"