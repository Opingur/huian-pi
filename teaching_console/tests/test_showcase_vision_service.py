import tempfile
import time
import unittest
from pathlib import Path

from teaching_console.services.showcase_vision_service import (
    NoHardwarePublisher,
    ShowcaseFrame,
    ShowcaseVisionWorker,
    bridge_publisher,
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


class ShowcaseVisionServiceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
