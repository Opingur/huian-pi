from __future__ import annotations

import unittest

from teaching_console.pages.trajectory_direction_page import format_heading
from teaching_console.project_paths import project_root
from teaching_console.services.trajectory_teaching_service import (
    LAYER_DIRECTION,
    LAYER_RAW,
    LAYER_TRACK,
    LAYER_TRAIL,
    TrajectoryTeachingService,
    active_track_ids,
    motion_display_data,
)
from teaching_console.services.vision_teaching_service import TeachingRow, VisionTeachingWorker, find_example_video


class FakeFrame:
    def copy(self):
        return FakeFrame()


class FakeCapture:
    def __init__(self) -> None:
        self.position = 0
        self.released = False

    def isOpened(self) -> bool:
        return True

    def release(self) -> None:
        self.released = True

    def get(self, property_id):
        return {1: 10.0, 2: 50, 3: 100, 4: 200}.get(property_id, 0)

    def set(self, property_id, value) -> None:
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


class FakeTrajectoryAnalyzer:
    def __init__(self) -> None:
        self.history: dict[int, list[tuple[float, float, float]]] = {}

    def update(self, tracks, width, height, source_time, _conflict_zone):
        result = {}
        for track in tracks:
            track_id = int(track["track_id"])
            trail = self.history.setdefault(track_id, [])
            trail.append((source_time, track["anchor_x"] / width, track["anchor_y"] / height))
            first = trail[0]
            current = trail[-1]
            moving = len(trail) > 1
            state = "STATIONARY" if track_id == 8 else ("MOVING" if moving else "UNCERTAIN")
            result[track_id] = {
                "track_id": track_id,
                "anchor_point": current[1:],
                "trail": list(trail),
                "dx": round(current[1] - first[1], 4),
                "dy": round(current[2] - first[2], 4),
                "speed_norm": 0.25 if moving else 0.0,
                "heading_angle": 42.5 if state == "MOVING" else None,
                "motion_state": state,
            }
        return result


def person(track_id: int, anchor_x: int, anchor_y: int) -> dict[str, object]:
    return {
        "class": "person", "confidence": 0.9,
        "x1": anchor_x - 10, "y1": anchor_y - 30,
        "x2": anchor_x + 10, "y2": anchor_y,
        "track_id": track_id, "anchor_x": anchor_x, "anchor_y": anchor_y,
    }


class TrajectoryTeachingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = project_root()
        self.tracker_builds = 0
        self.analyzers: list[FakeTrajectoryAnalyzer] = []
        frames = [[person(7, 20, 40)], [person(7, 40, 60)], [person(8, 50, 80)], []]

        def tracker_factory(*_args):
            self.tracker_builds += 1
            return FakeTracker(frames)

        def trajectory_factory(_config):
            analyzer = FakeTrajectoryAnalyzer()
            self.analyzers.append(analyzer)
            return analyzer

        self.service = TrajectoryTeachingService(
            self.root,
            cv2_loader=FakeCV2,
            tracker_factory=tracker_factory,
            trajectory_factory=trajectory_factory,
        )
        self.service.open_video(find_example_video(self.root))

    def tearDown(self) -> None:
        self.service.close()

    def test_track_layer_exposes_bottom_center_without_creating_trajectory(self) -> None:
        packet = self.service.read_trajectory_frame(0, LAYER_TRACK, sequential=False)
        self.assertEqual(packet.frame.rows[0].track_id, 7)
        self.assertEqual(packet.frame.rows[0].anchor, (20, 40))
        self.assertEqual(packet.motions, {})
        self.assertEqual(self.analyzers, [])

    def test_continuous_positions_enter_formal_trajectory_and_history_isolated(self) -> None:
        first = self.service.read_trajectory_frame(0, LAYER_TRAIL, sequential=False)
        second = self.service.read_trajectory_frame(1, LAYER_DIRECTION, sequential=True)
        third = self.service.read_trajectory_frame(2, LAYER_DIRECTION, sequential=True)
        self.assertEqual(len(first.motions[7]["trail"]), 1)
        self.assertEqual(len(second.motions[7]["trail"]), 2)
        self.assertEqual(second.motions[7]["motion_state"], "MOVING")
        self.assertEqual(third.motions[8]["motion_state"], "STATIONARY")
        self.assertEqual(set(self.analyzers[0].history), {7, 8})
        self.assertEqual(len(self.analyzers[0].history[7]), 2)
        self.assertEqual(len(self.analyzers[0].history[8]), 1)

    def test_display_data_contains_track_selector_anchor_trail_delta_and_heading(self) -> None:
        rows = (TeachingRow(1, 0.9, (10, 10, 30, 40), 7, (20, 40)), TeachingRow(2, 0.8, (40, 20, 60, 70), 8, (50, 70)))
        self.assertEqual(active_track_ids(rows), (7, 8))
        self.assertEqual(active_track_ids(()), ())
        data = motion_display_data({
            "track_id": 7, "anchor_point": (0.4, 0.3),
            "trail": [(1.0, 0.2, 0.1), (2.0, 0.4, 0.3)],
            "dx": 0.2, "dy": 0.2, "speed_norm": 0.1,
            "heading_angle": 42.5, "motion_state": "MOVING",
        }, 100, 200)
        self.assertEqual(data["anchor"], (40, 60))
        self.assertEqual((data["start"], data["end"]), ((20, 20), (40, 60)))
        self.assertEqual((data["dx_pixels"], data["dy_pixels"]), (20, 40))
        self.assertEqual(format_heading(data["heading_angle"]), "42.5°")

    def test_motion_states_keep_missing_heading_explicit(self) -> None:
        for state in ("UNCERTAIN", "STATIONARY", "MOVING"):
            data = motion_display_data({
                "track_id": 7, "anchor_point": (0.1, 0.1), "trail": [],
                "motion_state": state, "heading_angle": 20.0 if state == "MOVING" else None,
            }, 100, 100)
            self.assertEqual(data["motion_state"], state)
            self.assertEqual(format_heading(data["heading_angle"]), "20.0°" if state == "MOVING" else "—")

    def test_seek_and_video_change_reset_tracker_and_trajectory(self) -> None:
        self.service.read_trajectory_frame(0, LAYER_TRAIL, sequential=False)
        self.service.read_trajectory_frame(1, LAYER_TRAIL, sequential=True)
        jumped = self.service.read_trajectory_frame(0, LAYER_TRAIL, sequential=False)
        self.assertTrue(jumped.trajectory_reset)
        self.assertEqual(self.tracker_builds, 2)
        self.assertEqual(len(self.analyzers), 2)
        self.service.open_video(find_example_video(self.root))
        changed = self.service.read_trajectory_frame(0, LAYER_TRAIL, sequential=False)
        self.assertTrue(changed.trajectory_reset)
        self.assertEqual(self.tracker_builds, 3)
        self.assertEqual(len(self.analyzers), 3)

    def test_raw_and_empty_tracks_do_not_retain_previous_data(self) -> None:
        self.service.read_trajectory_frame(0, LAYER_TRAIL, sequential=False)
        raw = self.service.read_trajectory_frame(1, LAYER_RAW)
        self.assertEqual(raw.motions, {})
        self.assertIsNone(self.service._trajectory)
        self.service.read_trajectory_frame(0, LAYER_TRAIL, sequential=False)
        self.service.read_trajectory_frame(1, LAYER_TRAIL, sequential=True)
        self.service.read_trajectory_frame(2, LAYER_TRAIL, sequential=True)
        empty = self.service.read_trajectory_frame(3, LAYER_TRAIL, sequential=True)
        self.assertEqual(empty.frame.rows, ())
        self.assertEqual(empty.motions, {})

    def test_worker_close_calls_service_close(self) -> None:
        class CloseOnlyService:
            closed = False

            def close(self):
                self.closed = True

        service = CloseOnlyService()
        worker = VisionTeachingWorker(service)
        worker.close()
        self.assertTrue(service.closed)


if __name__ == "__main__":
    unittest.main()

