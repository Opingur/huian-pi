import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np

from rpi_app.services.demo_engine import DemoEngine, load_demo_events, scan_demo_cases
from rpi_app.services.runtime_snapshot import RuntimeSnapshotPublisher, load_latest_frame, load_latest_status
from rpi_app.services.teacher_server import TeacherRuntime, make_handler


class FakePublisher:
    def __init__(self): self.sent = []; self.resets = 0; self.closed = False
    def send_status(self, status, *, source_timestamp=None): self.sent.append((dict(status), source_timestamp)); return True
    def reset_send_interval(self): self.resets += 1
    def close(self): self.closed = True


class FakeCapture:
    def __init__(self): self.index = 0
    def isOpened(self): return True
    def read(self):
        if self.index >= 2: return False, None
        self.index += 1; return True, np.zeros((20, 30, 3), dtype=np.uint8)
    def get(self, key):
        if key == 5: return 1.0
        if key == 0: return self.index * 1000.0
        return 0.0
    def release(self): pass


def make_case(root: Path) -> None:
    case = root / "000327"; case.mkdir()
    (case / "dashboard.mp4").write_bytes(b"fake")
    (case / "cover.jpg").write_bytes(b"jpeg")
    (case / "events.jsonl").write_text(
        json.dumps({"time": 0.0, "vision_risk": "NORMAL", "running_event": False, "running_count": 0, "future_field": "ignored"}) + "\n" +
        json.dumps({"time": 1.0, "vision_risk": "CROWD", "running_event": False, "running_count": 0}) + "\n", encoding="utf-8")
    (case / "summary.json").write_text(json.dumps({"case_id": "000327", "title": "人流监测示例", "duration_seconds": 2.0, "source_fps": 1.0}), encoding="utf-8")


class TeacherServiceTests(unittest.TestCase):
    def test_snapshot_is_atomic_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            publisher = RuntimeSnapshotPublisher(Path(directory), enabled=True, interval_seconds=0.05)
            self.assertTrue(publisher.publish({"total_people": 3, "vision_risk": "NORMAL"}, np.zeros((10, 10, 3), dtype=np.uint8), source_time=1.25))
            self.assertEqual(load_latest_status(Path(directory))["source_time"], 1.25)
            self.assertTrue(load_latest_frame(Path(directory)).startswith(b"\xff\xd8"))

    def test_scan_and_demo_timeline_pause_restart_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); make_case(root); publisher = FakePublisher(); now = [0.0]
            engine = DemoEngine(root, publisher, capture_factory=lambda _path: FakeCapture(), jpeg_encoder=lambda _frame: b"jpeg", clock=lambda: now[0], auto_thread=False)
            self.assertEqual(engine.cases()[0]["case_id"], "000327")
            self.assertEqual(engine.start("000327")["state"], "playing")
            self.assertEqual(publisher.sent[-1][0]["vision_risk"], "NORMAL")
            engine.tick(); self.assertEqual(engine.frame(), b"jpeg")
            self.assertEqual(engine.pause()["state"], "paused")
            now[0] = 1.0; engine.tick(); self.assertEqual(engine.state()["position_seconds"], 1.0)
            self.assertEqual(engine.resume()["state"], "playing")
            engine.tick(); self.assertEqual(engine.state()["vision_risk"], "CROWD")
            self.assertEqual(engine.restart()["position_seconds"], 0.0)
            self.assertEqual(engine.stop()["vision_risk"], "NORMAL")
            self.assertGreaterEqual(publisher.resets, 3)
            engine.close(); self.assertTrue(publisher.closed)

    def test_events_keep_unknown_future_fields_without_breaking(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); make_case(root)
            event = load_demo_events(root / "000327" / "events.jsonl")[0]
            self.assertEqual(event["future_field"], "ignored")
            self.assertEqual(scan_demo_cases(root)[0].title, "人流监测示例")

    def test_http_health_status_cases_frame_and_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); make_case(root); publisher = FakePublisher()
            engine = DemoEngine(root, publisher, capture_factory=lambda _path: FakeCapture(), jpeg_encoder=lambda _frame: b"jpeg", auto_thread=False)
            runtime = TeacherRuntime(root, root / "runtime", demo_engine=engine)
            from http.server import ThreadingHTTPServer
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(runtime)); thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                self.assertTrue(json.loads(urlopen(base + "/api/health", timeout=1).read())["ok"])
                self.assertEqual(json.loads(urlopen(base + "/api/status", timeout=1).read())["mode"], "idle")
                self.assertEqual(json.loads(urlopen(base + "/api/cases", timeout=1).read())["cases"][0]["case_id"], "000327")
                request = Request(base + "/api/demo/start", data=b'{"case_id":"000327"}', method="POST", headers={"Content-Type": "application/json"})
                self.assertEqual(json.loads(urlopen(request, timeout=1).read())["state"], "playing")
                engine.tick(); self.assertEqual(urlopen(base + "/api/frame.jpg", timeout=1).read(), b"jpeg")
            finally:
                server.shutdown(); server.server_close(); runtime.close()


if __name__ == "__main__": unittest.main()