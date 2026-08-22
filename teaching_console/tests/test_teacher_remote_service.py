import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

from teaching_console.pages.demo_showcase_page import demo_state_text
from teaching_console.services.teacher_remote_service import (
    DEFAULT_PI_URL, TeacherRemoteClient, TeacherRemoteError, TeacherRemoteSettings, TeacherRemoteSettingsStore,
    demo_case_row, direct_urlopen, live_status_rows, normalize_base_url,
)


class Response:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self): return self.data


class TeacherRemoteClientTests(unittest.TestCase):
    def test_default_and_persisted_address(self):
        self.assertEqual(normalize_base_url(""), DEFAULT_PI_URL)
        self.assertEqual(normalize_base_url("192.168.1.8:8765/"), "http://192.168.1.8:8765")
        with tempfile.TemporaryDirectory() as directory:
            store = TeacherRemoteSettingsStore(Path(directory))
            store.save(TeacherRemoteSettings("100.70.1.2:8765"))
            self.assertEqual(store.load().base_url, "http://100.70.1.2:8765")

    def test_default_client_bypasses_windows_proxy(self):
        client = TeacherRemoteClient("100.111.124.9:8765")
        self.assertIs(client.opener, direct_urlopen)

    def test_json_frame_and_post_commands(self):
        calls = []
        def opener(request, timeout):
            calls.append((request.full_url, request.method, request.data, timeout))
            if request.full_url.endswith("frame.jpg"): return Response(b"jpeg")
            if request.full_url.endswith("cases"): return Response(b'{"cases":[{"case_id":"000327"}]}')
            return Response(b'{"ok":true,"state":"playing"}')
        client = TeacherRemoteClient("pi.local:8765", opener=opener)
        self.assertTrue(client.health()["ok"])
        self.assertEqual(client.frame(), b"jpeg")
        self.assertEqual(client.cases()[0]["case_id"], "000327")
        self.assertEqual(client.demo_command("start", case_id="000327")["state"], "playing")
        self.assertIn(b"000327", calls[-1][2])

    def test_offline_never_raises_outside_controlled_error(self):
        def offline(_request, timeout): raise URLError("offline")
        with self.assertRaises(TeacherRemoteError): TeacherRemoteClient("pi.local", opener=offline).status()

    def test_display_helpers(self):
        rows = dict(live_status_rows({"total_people": 8, "vision_risk": "CROWD", "crowd_index": 0.31, "running_count": 1, "esp32_online": True, "camera_online": True, "source_time": 2.0}))
        self.assertEqual(rows["当前人数"], "8")
        self.assertEqual(rows["ESP32"], "在线")
        self.assertEqual(demo_case_row({"case_id": "000327", "title": "示例", "duration": 39.7}), ("000327", "示例", "39.7 s"))
        self.assertIn("000327", demo_state_text({"state": "paused", "case_id": "000327", "position_seconds": 2}))


if __name__ == "__main__": unittest.main()