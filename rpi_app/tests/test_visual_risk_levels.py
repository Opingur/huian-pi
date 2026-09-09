from vision.video_runner import _apply_flow_risk, _finalize_visual_alarm


def test_single_directional_flow_is_a_blue_warning_not_a_yellow_crowd_alarm():
    risk = _apply_flow_risk("NORMAL", {"single_flow_crowd_risk": True})
    assert risk == "WARNING"
    assert _finalize_visual_alarm(risk, "NONE", "none") == ("WARNING", "BLUE", "vision_risk_warning")


def test_only_convergence_or_high_crowd_metric_reaches_crowd_alarm():
    assert _apply_flow_risk("WARNING", {"convergence_risk": False}) == "WARNING"
    assert _apply_flow_risk("CROWD", {"convergence_risk": False}) == "CROWD"
    assert _apply_flow_risk("NORMAL", {"convergence_risk": True}) == "CROWD"
