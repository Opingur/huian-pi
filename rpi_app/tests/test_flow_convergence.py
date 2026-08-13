import unittest

from decision.flow_analysis import FlowRiskAnalyzer


class FlowConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = FlowRiskAnalyzer({
            "min_group_people": 2, "min_total_people": 4,
            "min_heading_difference_deg": 45, "max_current_distance_norm": 0.8,
            "max_future_distance_norm": 0.16, "prediction_horizon_seconds": 2.0,
            "max_convergence_eta_seconds": 3.0, "convergence_score_threshold": 0.50,
            "min_group_stability": 0.6,
        })

    @staticmethod
    def motion(track_id, point, heading, speed=0.10):
        return {"track_id": track_id, "anchor_point": point, "heading_angle": heading,
                "speed_norm": speed, "motion_state": "MOVING", "trail": [(0, 0, 0)] * 3}

    def analyse(self, items):
        motions = [item[0] for item in items]
        groups = {item[0]["track_id"]: {"label": item[1], "color": (0, 0, 0)} for item in items}
        return self.analyzer.analyze(motions, {"prediction_valid": False, "predicted_people": {}}, groups)

    def test_a_parallel_same_direction_is_not_convergence(self):
        result = self.analyse([(self.motion(1, (0.20, 0.30), 0), "A"), (self.motion(2, (0.22, 0.32), 0), "A"), (self.motion(3, (0.20, 0.55), 0), "B"), (self.motion(4, (0.22, 0.57), 0), "B")])
        self.assertFalse(result["convergence_risk"])

    def test_b_different_direction_but_far_is_not_convergence(self):
        result = self.analyse([(self.motion(1, (0.05, 0.20), 0), "A"), (self.motion(2, (0.07, 0.22), 0), "A"), (self.motion(3, (0.92, 0.80), 180), "B"), (self.motion(4, (0.94, 0.82), 180), "B")])
        self.assertFalse(result["convergence_risk"])

    def test_c_opposite_but_passing_apart_is_not_convergence(self):
        result = self.analyse([(self.motion(1, (0.25, 0.30), 0), "A"), (self.motion(2, (0.27, 0.32), 0), "A"), (self.motion(3, (0.45, 0.55), 180), "B"), (self.motion(4, (0.47, 0.57), 180), "B")])
        self.assertFalse(result["convergence_risk"])

    def test_d_two_main_groups_converging_on_same_area_is_true(self):
        result = self.analyse([(self.motion(1, (0.25, 0.50), 0), "A"), (self.motion(2, (0.27, 0.50), 0), "A"), (self.motion(3, (0.65, 0.50), 180), "B"), (self.motion(4, (0.67, 0.50), 180), "B")])
        self.assertTrue(result["convergence_risk"])
        self.assertIsNotNone(result["convergence_eta"])

    def test_e_too_few_people_is_not_convergence(self):
        result = self.analyse([(self.motion(1, (0.25, 0.50), 0), "A"), (self.motion(2, (0.65, 0.50), 180), "B")])
        self.assertFalse(result["convergence_risk"])


if __name__ == "__main__":
    unittest.main()
