from __future__ import annotations

from dataclasses import dataclass
import unittest

from teaching_console.project_paths import project_root
from teaching_console.services.trend_crowd_teaching_service import (
    TrendCrowdTeachingService,
    load_trend_crowd_config,
)
from teaching_console.services.vision_teaching_service import VisionTeachingWorker, find_example_video


class FakeFrame:
    def copy(self):
        return FakeFrame()


class FakeCapture:
    def __init__(self) -> None:
        self.position = 0

    def isOpened(self):
        return True

    def release(self):
        pass

    def get(self, property_id):
        return {1: 1.0, 2: 40, 3: 100, 4: 100}.get(property_id, 0)

    def set(self, property_id, value):
        if property_id == 5:
            self.position = int(value)

    def read(self):
        return True, FakeFrame()


class FakeCV2:
    CAP_PROP_FPS = 1
    CAP_PROP_FRAME_COUNT = 2
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_POS_FRAMES = 5
    FONT_HERSHEY_SIMPLEX = 6

    def VideoCapture(self, _path):
        return FakeCapture()

    @staticmethod
    def rectangle(*_args):
        pass

    @staticmethod
    def putText(*_args):
        pass

    @staticmethod
    def circle(*_args):
        pass


class FakeTracker:
    def __init__(self, frames) -> None:
        self.frames = list(frames)
        self.index = 0

    def track(self, _frame):
        item = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return item


@dataclass(frozen=True)
class FakeTrend:
    left_people: int
    right_people: int
    total_people: int
    occupancy_growth: float
    direction_conflict: bool = False


class FakePeopleFlow:
    def __init__(self) -> None:
        self.history = []

    def update(self, left, right, now):
        self.history.append((now, left, right))
        first = self.history[0][1] + self.history[0][2]
        total = left + right
        return FakeTrend(left, right, total, float(total - first)), True


class FakePredictor:
    def predict(self, history, current_people):
        if len(history) < 2:
            return {"prediction_valid": False, "prediction_slope": None, "predicted_people": {10: None, 20: None, 30: None}}
        first = history[0][1] + history[0][2]
        slope = 0.5 if current_people > first else (-0.5 if current_people < first else 0.0)
        return {
            "prediction_valid": True,
            "prediction_slope": slope,
            "predicted_people": {10: current_people + slope * 10, 20: current_people + slope * 20, 30: current_people + slope * 30},
        }


class FakeTrajectory:
    def update(self, tracks, width, height, now, _zone):
        return {
            int(track["track_id"]): {
                "track_id": int(track["track_id"]), "anchor_point": (track["anchor_x"] / width, track["anchor_y"] / height),
                "trail": [(now, track["anchor_x"] / width, track["anchor_y"] / height)],
                "speed_norm": 0.1, "heading_angle": 30.0, "motion_state": "MOVING",
            }
            for track in tracks
        }


class FakeFlowRisk:
    def analyze(self, motions, forecast, groups):
        return {"convergence_score": 0.4, "convergence_risk": False, "single_flow_crowd_risk": False, "predicted_single_flow_warning": False}


class FakeRiskEngine:
    def evaluate(self, _left, _right, _growth, _conflict, index):
        return "NORMAL" if index < 0.3 else ("WARNING" if index < 0.6 else "DANGER")


def person(track_id, center_x, anchor_y=80):
    return {"class": "person", "confidence": 0.9, "x1": center_x - 5, "y1": anchor_y - 20, "x2": center_x + 5, "y2": anchor_y, "track_id": track_id, "anchor_x": center_x, "anchor_y": anchor_y}


class TrendCrowdTeachingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = project_root()
        self.flow_builds = 0
        self.tracker_builds = 0
        self.frames = [[], [person(1, 20)], [person(1, 20), person(2, 80)], [person(1, 20)], []]

        def tracker_factory(*_args):
            self.tracker_builds += 1
            return FakeTracker(self.frames)

        def flow_factory(_config):
            self.flow_builds += 1
            return FakePeopleFlow()

        def fake_index(left, right, growth, _conflict, config, convergence):
            total = left + right
            index = 0.1 if total == 0 else (0.4 if total == 1 else 0.8)
            self.last_index_args = (left, right, growth, config, convergence)
            return {"index": index, "density_score": 0.25, "growth_score": 0.5, "conflict_score": convergence}

        def formal_like_mapper(base, metrics):
            if metrics["convergence_risk"] or base in {"WARNING", "CROWD", "DANGER"} or metrics["single_flow_crowd_risk"] or metrics["predicted_single_flow_warning"]:
                return "CROWD"
            return "NORMAL"

        self.service = TrendCrowdTeachingService(
            self.root,
            cv2_loader=FakeCV2,
            tracker_factory=tracker_factory,
            flow_factory=flow_factory,
            predictor_factory=lambda _config: FakePredictor(),
            trajectory_factory=lambda _config: FakeTrajectory(),
            flow_risk_factory=lambda _config: FakeFlowRisk(),
            crowd_index_calculator=fake_index,
            risk_engine_factory=lambda _config: FakeRiskEngine(),
            risk_mapper=formal_like_mapper,
            group_builder=lambda motions: {track_id: {"label": "A"} for track_id in motions},
        )
        self.service.open_video(find_example_video(self.root))

    def tearDown(self) -> None:
        self.service.close()

    def test_history_left_right_and_empty_frame_are_real_current_values(self) -> None:
        first = self.service.read_trend_frame(0, sequential=False)
        second = self.service.read_trend_frame(1, sequential=True)
        third = self.service.read_trend_frame(2, sequential=True)
        self.assertEqual((first.trend.left_people, first.trend.right_people, first.trend.total_people), (0, 0, 0))
        self.assertEqual((second.trend.left_people, second.trend.right_people, second.trend.total_people), (1, 0, 1))
        self.assertEqual((third.trend.left_people, third.trend.right_people, third.trend.total_people), (1, 1, 2))
        self.assertEqual(len(third.history), 3)
        self.assertEqual(self.last_index_args[4], 0.4)

    def test_prediction_fields_cover_insufficient_positive_and_negative_history(self) -> None:
        insufficient = self.service.read_trend_frame(0, sequential=False)
        positive = self.service.read_trend_frame(1, sequential=True)
        self.assertFalse(insufficient.forecast["prediction_valid"])
        self.assertIsNone(insufficient.forecast["prediction_slope"])
        self.assertTrue(positive.forecast["prediction_valid"])
        self.assertEqual((positive.forecast["prediction_slope"], positive.forecast["predicted_people"][10], positive.forecast["predicted_people"][20], positive.forecast["predicted_people"][30]), (0.5, 6.0, 11.0, 16.0))
        self.frames[:] = [[person(1, 20), person(2, 80)], [person(1, 20)]]
        self.service.read_trend_frame(0, sequential=False)
        negative = self.service.read_trend_frame(1, sequential=True)
        self.assertEqual(negative.forecast["prediction_slope"], -0.5)

    def test_formal_config_weights_and_risk_states_are_not_danger(self) -> None:
        config = load_trend_crowd_config(self.root)
        self.assertEqual((config.crowd_index["weight_density"], config.crowd_index["weight_growth"], config.crowd_index["weight_conflict"]), (0.5, 0.3, 0.2))
        normal = self.service.read_trend_frame(0, sequential=False)
        warning_base = self.service.read_trend_frame(1, sequential=True)
        crowd_base = self.service.read_trend_frame(2, sequential=True)
        self.assertEqual((normal.base_risk, warning_base.base_risk, crowd_base.base_risk), ("NORMAL", "WARNING", "DANGER"))
        self.assertEqual((normal.risk_state, warning_base.risk_state, crowd_base.risk_state), ("NORMAL", "CROWD", "CROWD"))
        self.assertNotEqual(crowd_base.risk_state, "DANGER")

    def test_seek_and_video_change_reset_history_and_tracker(self) -> None:
        self.service.read_trend_frame(0, sequential=False)
        self.service.read_trend_frame(1, sequential=True)
        jumped = self.service.read_trend_frame(0, sequential=False)
        self.assertTrue(jumped.reset)
        self.assertEqual(len(jumped.history), 1)
        self.assertEqual((self.tracker_builds, self.flow_builds), (2, 2))
        self.service.open_video(find_example_video(self.root))
        changed = self.service.read_trend_frame(0, sequential=False)
        self.assertTrue(changed.reset)
        self.assertEqual((self.tracker_builds, self.flow_builds), (3, 3))

    def test_observed_history_survives_jumps_but_formal_history_resets(self) -> None:
        packet = None
        for second in range(6):
            packet = self.service.read_trend_frame(second, sequential=second > 0)
        self.assertEqual(set(dict(packet.observed_history)), set(range(6)))
        jumped = self.service.read_trend_frame(10, sequential=False)
        self.assertEqual(len(jumped.history), 1)
        self.assertFalse(jumped.forecast["prediction_valid"])
        self.assertEqual(set(dict(jumped.observed_history)), set(range(6)) | {10})
        for second in (11, 12):
            jumped = self.service.read_trend_frame(second, sequential=True)
        self.assertEqual(set(dict(jumped.observed_history)), set(range(6)) | {10, 11, 12})
        back = self.service.read_trend_frame(5, sequential=False)
        self.assertEqual(len(back.history), 1)
        self.assertEqual(set(dict(back.observed_history)), set(range(6)) | {10, 11, 12})
        for second in (6, 7, 8):
            back = self.service.read_trend_frame(second, sequential=True)
        self.assertEqual(set(dict(back.observed_history)), set(range(9)) | {10, 11, 12})
        complete = self.service.read_trend_frame(9, sequential=True)
        self.assertEqual(set(dict(complete.observed_history)), set(range(13)))
        self.service.reload_models()
        self.assertEqual(self.service.observed_history, {})

    def test_worker_close_calls_service_close(self) -> None:
        class CloseOnlyService:
            closed = False

            def close(self):
                self.closed = True

        service = CloseOnlyService(); worker = VisionTeachingWorker(service); worker.close()
        self.assertTrue(service.closed)


if __name__ == "__main__":
    unittest.main()

