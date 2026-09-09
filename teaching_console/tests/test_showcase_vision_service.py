import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

from teaching_console.services.showcase_vision_service import (
    NoHardwarePublisher,
    ShowcaseFrame,
    ShowcaseVisionWorker,
    apply_showcase_fire_profile,
    apply_low_resolution_presentation_profile,
    apply_showcase_running_profile,
    apply_showcase_tracking_profile,
    bridge_publisher,
    prepare_low_resolution_showcase_frame,
    should_publish_showcase_status,
)


class FakePublisher:
    def __init__(self, endpoint, key):
        self.endpoint, self.key = endpoint, key
        self.sent = []
        self.closed = False
    def send_status(self, status, *, source_timestamp=None):
        self.sent.append((dict(status), source_timestamp)); return True
    def poll_esp32_status(self, **_kwargs): return None
    def esp32_status_is_stale(self, **_kwargs): return True
    def close(self): self.closed = True


class FailOncePublisher(FakePublisher):
    def __init__(self, endpoint, key):
        super().__init__(endpoint, key)
        self.reset_calls = 0
        self._results = [False, True]

    def reset_send_interval(self):
        self.reset_calls += 1

    def send_status(self, status, *, source_timestamp=None):
        self.sent.append((dict(status), source_timestamp))
        return self._results.pop(0)


class FakeProcessor:
    def __init__(self, publisher): self.publisher, self.closed = publisher, False
    def process_frame(self, frame, timestamp):
        return frame, {"total_people": 2, "vision_risk": "WARNING"}, True
    def close(self): self.closed = True; self.publisher.close()


class FakeCapture:
    def __init__(self, _path): self.reads, self.released = 0, False
    def isOpened(self): return True
    def get(self, flag): return 10.0 if flag == 5 else 100.0
    def read(self):
        self.reads += 1
        return (True, object()) if self.reads == 1 else (False, None)
    def release(self): self.released = True


class FakeCv2:
    CAP_PROP_FPS = 5
    CAP_PROP_POS_MSEC = 0
    VideoCapture = FakeCapture


class TwoFrameCapture(FakeCapture):
    def read(self):
        self.reads += 1
        return (True, object()) if self.reads <= 2 else (False, None)


class TwoFrameCv2:
    CAP_PROP_FPS = 5
    CAP_PROP_POS_MSEC = 0
    VideoCapture = TwoFrameCapture


class ActiveWarningProcessor(FakeProcessor):
    def process_frame(self, frame, timestamp):
        return frame, {"total_people": 2, "vision_risk": "WARNING"}, False


class TimedCapture:
    def __init__(self, _path):
        self.reads, self.released = 0, False

    def isOpened(self): return True

    def get(self, flag): return 20.0 if flag == 5 else 0.0

    def read(self):
        self.reads += 1
        return (True, object()) if self.reads <= 4 else (False, None)

    def release(self): self.released = True


class TimedCv2:
    CAP_PROP_FPS = 5
    CAP_PROP_POS_MSEC = 0
    VideoCapture = TimedCapture


class SeekCapture:
    last_instance = None

    def __init__(self, _path):
        self.reads, self.released, self.position_ms, self.seek_values = 0, False, 0.0, []
        type(self).last_instance = self

    def isOpened(self): return True

    def get(self, flag):
        if flag == 5: return 10.0
        if flag == 0: return self.position_ms
        if flag == 7: return 100.0
        return 0.0

    def set(self, flag, value):
        if flag == 0:
            self.position_ms = value
            self.seek_values.append(value)
        return True

    def grab(self): return True

    def read(self):
        self.reads += 1
        return (True, object()) if self.reads <= 5 else (False, None)

    def release(self): self.released = True


class SeekCv2:
    CAP_PROP_FPS = 5
    CAP_PROP_POS_MSEC = 0
    CAP_PROP_FRAME_COUNT = 7
    VideoCapture = SeekCapture


class SeekProcessor:
    def __init__(self, publisher):
        self.publisher, self.closed = publisher, False

    def process_frame(self, frame, timestamp):
        return frame, {"total_people": 1, "vision_risk": "NORMAL"}, False

    def close(self): self.closed = True; self.publisher.close()


class LiveProcessor:
    def __init__(self, publisher):
        self.publisher, self.sync_calls, self.live_calls, self.closed = publisher, 0, 0, False

    def process_frame(self, frame, timestamp):
        self.sync_calls += 1
        time.sleep(0.15)
        return frame, {"total_people": 2, "vision_risk": "WARNING"}, False

    def process_live_frame(self, frame, timestamp):
        self.live_calls += 1
        return frame, {"total_people": 2, "vision_risk": "WARNING"}, False

    def close(self): self.closed = True; self.publisher.close()


class ShowcaseVisionServiceTests(unittest.TestCase):
    def test_hardware_status_is_immediate_on_risk_transition_without_snapshot(self):
        self.assertTrue(should_publish_showcase_status(
            {"vision_risk": "WARNING"}, snapshot_saved=False,
            previous_risk="NORMAL", last_publish_monotonic=2.0, now_monotonic=2.1,
        ))
        self.assertTrue(should_publish_showcase_status(
            {"vision_risk": "NORMAL"}, snapshot_saved=False,
            previous_risk="WARNING", last_publish_monotonic=2.0, now_monotonic=2.1,
        ))

    def test_hardware_status_keeps_active_warning_lease_alive(self):
        status = {"vision_risk": "CROWD"}
        self.assertFalse(should_publish_showcase_status(
            status, snapshot_saved=False, previous_risk="CROWD",
            last_publish_monotonic=10.0, now_monotonic=10.9,
        ))
        self.assertTrue(should_publish_showcase_status(
            status, snapshot_saved=False, previous_risk="CROWD",
            last_publish_monotonic=10.0, now_monotonic=11.0,
        ))

    def test_normal_status_still_uses_regular_snapshot_updates(self):
        self.assertFalse(should_publish_showcase_status(
            {"vision_risk": "NORMAL"}, snapshot_saved=False,
            previous_risk="NORMAL", last_publish_monotonic=10.0, now_monotonic=20.0,
        ))
        self.assertTrue(should_publish_showcase_status(
            {"vision_risk": "NORMAL"}, snapshot_saved=True,
            previous_risk="NORMAL", last_publish_monotonic=10.0, now_monotonic=10.1,
        ))
    def test_worker_keeps_latest_requested_seek(self):
        worker = ShowcaseVisionWorker(Path("."), cv2_loader=lambda: FakeCv2)

        worker.seek(3.0)
        worker.seek(12.5)

        self.assertEqual(worker._take_seek_request(), 12.5)
        self.assertIsNone(worker._take_seek_request())

    def test_worker_rebuilds_analysis_session_after_seek(self):
        created = []

        def components(_root, publisher):
            processor = SeekProcessor(publisher)
            created.append(processor)
            return processor, {}

        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "case.mp4"; video.write_bytes(b"placeholder")
            worker = ShowcaseVisionWorker(Path(directory), components_factory=components, cv2_loader=lambda: SeekCv2)
            worker.start(video)
            deadline = time.monotonic() + 1.0
            events = []
            while time.monotonic() < deadline:
                while not worker.events.empty(): events.append(worker.events.get_nowait())
                if any(event.kind == "started" for event in events): break
                time.sleep(0.01)
            worker.pause(True)
            worker.seek(4.0)
            worker.pause(False)
            while time.monotonic() < deadline:
                while not worker.events.empty(): events.append(worker.events.get_nowait())
                if any(event.kind == "finished" for event in events): break
                time.sleep(0.01)
            worker.stop()

        self.assertEqual(len(created), 2)
        self.assertTrue(created[0].closed)
        self.assertIn(4000.0, SeekCapture.last_instance.seek_values)
        self.assertTrue(any(event.kind == "seeked" for event in events))

    def test_low_resolution_source_is_prepared_before_annotations(self):
        source = np.zeros((240, 320, 3), dtype=np.uint8)

        prepared = prepare_low_resolution_showcase_frame(cv2, source)

        self.assertEqual(prepared.shape, (740, 1280, 3))

    def test_native_resolution_source_is_not_resized(self):
        source = np.zeros((720, 1280, 3), dtype=np.uint8)

        self.assertIs(prepare_low_resolution_showcase_frame(cv2, source), source)

    def test_low_resolution_profile_hides_debug_overlays_only(self):
        processor = type("Processor", (), {"config": {"display": {"show_track_id": True}}})()

        apply_low_resolution_presentation_profile(processor)

        self.assertFalse(processor.config["display"]["show_track_id"])
        self.assertFalse(processor.config["display"]["show_trajectory"])
        self.assertFalse(processor.config["display"]["show_direction_arrow"])

    def test_showcase_running_profile_overrides_only_copied_display_config(self):
        config = {"running_detection": {"enter_threshold": 1.0, "release_seconds": 0.5}}

        apply_showcase_running_profile(config, {"enter_threshold": 0.7, "pixel_enter_threshold": 105.0})

        self.assertEqual(config["running_detection"]["enter_threshold"], 0.7)
        self.assertEqual(config["running_detection"]["release_seconds"], 0.5)
        self.assertEqual(config["running_detection"]["pixel_enter_threshold"], 105.0)
    def test_showcase_tracking_profile_is_limited_to_the_copied_config(self):
        config = {"confidence": 0.35, "tracking": {"tracker": "bytetrack.yaml", "imgsz": 320}}

        apply_showcase_tracking_profile(config, Path("project"))

        self.assertEqual(config["confidence"], 0.30)
        self.assertEqual(config["tracking"]["imgsz"], 448)
        self.assertEqual(
            config["tracking"]["tracker"],
            str(Path("project") / "rpi_app" / "configs" / "showcase_bytetrack.yaml"),
        )

    def test_showcase_fire_profile_restores_tiled_detection_without_mutating_formal_config(self):
        formal_config = {
            "fire_detection": {
                "interval_seconds": 2.5,
                "tiled_inference": False,
                "confirmation_hits": 3,
                "confidence": 0.18,
            }
        }
        showcase_config = dict(formal_config)

        apply_showcase_fire_profile(showcase_config)

        self.assertEqual(showcase_config["fire_detection"]["interval_seconds"], 0.3)
        self.assertTrue(showcase_config["fire_detection"]["tiled_inference"])
        self.assertEqual(showcase_config["fire_detection"]["confirmation_hits"], 3)
        self.assertEqual(showcase_config["fire_detection"]["confidence"], 0.18)
        self.assertEqual(formal_config["fire_detection"]["interval_seconds"], 2.5)
        self.assertFalse(formal_config["fire_detection"]["tiled_inference"])
    def test_missing_bridge_secret_never_constructs_serial_publisher(self):
        self.assertIsInstance(bridge_publisher("http://pi:8781/api/vision", ""), NoHardwarePublisher)

    def test_bridge_publisher_is_network_factory_when_explicitly_configured(self):
        publisher = bridge_publisher("http://pi:8781/api/vision", "secret", factory=FakePublisher)
        self.assertEqual((publisher.endpoint, publisher.key), ("http://pi:8781/api/vision", "secret"))

    def test_worker_processes_formal_packet_and_releases_remote_lease(self):
        created = []
        def components(_root, publisher):
            processor = FakeProcessor(publisher); created.append(processor)
            return processor, {}
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "case.mp4"; video.write_bytes(b"placeholder")
            worker = ShowcaseVisionWorker(
                Path(directory), components_factory=components,
                publisher_factory=FakePublisher, cv2_loader=lambda: FakeCv2,
            )
            worker.start(video, bridge_endpoint="http://pi:8781/api/vision", bridge_key="secret")
            deadline = time.monotonic() + 2.0
            events = []
            while time.monotonic() < deadline:
                while not worker.events.empty(): events.append(worker.events.get_nowait())
                if any(event.kind == "finished" for event in events): break
                time.sleep(0.01)
            worker.stop()
        packets = [event.value for event in events if event.kind == "frame"]
        self.assertEqual(len(packets), 1)
        self.assertIsInstance(packets[0], ShowcaseFrame)
        self.assertEqual(created[0].publisher.sent[0][0]["vision_risk"], "WARNING")
        self.assertTrue(created[0].closed)


    def test_worker_uses_nonblocking_live_processor_at_source_speed(self):
        created = []


        def components(_root, publisher):
            processor = LiveProcessor(publisher); created.append(processor)
            return processor, {}

        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "case.mp4"; video.write_bytes(b"placeholder")
            worker = ShowcaseVisionWorker(
                Path(directory), components_factory=components,
                cv2_loader=lambda: TimedCv2,
            )
            started = time.monotonic()
            worker.start(video)
            deadline = started + 2.0
            events = []
            while time.monotonic() < deadline:
                while not worker.events.empty(): events.append(worker.events.get_nowait())
                if any(event.kind == "finished" for event in events): break
                time.sleep(0.01)
            elapsed = time.monotonic() - started
            worker.stop()

        self.assertTrue(any(event.kind == "finished" for event in events))
        self.assertEqual(created[0].sync_calls, 0)
        self.assertEqual(created[0].live_calls, 4)
        self.assertLess(elapsed, 0.45)
    def test_worker_retries_failed_active_alert_without_waiting_for_telemetry_interval(self):
        created = []

        def components(_root, publisher):
            processor = ActiveWarningProcessor(publisher)
            created.append(processor)
            return processor, {}

        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "case.mp4"
            video.write_bytes(b"placeholder")
            worker = ShowcaseVisionWorker(
                Path(directory), components_factory=components,
                publisher_factory=FailOncePublisher, cv2_loader=lambda: TwoFrameCv2,
            )
            worker.start(video, bridge_endpoint="http://pi:8781/api/vision", bridge_key="secret")
            deadline = time.monotonic() + 2.0
            events = []
            while time.monotonic() < deadline:
                while not worker.events.empty():
                    events.append(worker.events.get_nowait())
                if any(event.kind == "finished" for event in events):
                    break
                time.sleep(0.01)
            worker.stop()

        publisher = created[0].publisher
        self.assertTrue(any(event.kind == "finished" for event in events))
        self.assertEqual(len(publisher.sent), 2)
        self.assertEqual(publisher.reset_calls, 2)
        self.assertLess(publisher.sent[0][1], publisher.sent[1][1])
        self.assertTrue(created[0].closed)



if __name__ == "__main__":
    unittest.main()
