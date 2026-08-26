import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from rpi_app.web.runtime_adapter import RuntimeStatusAdapter
from rpi_app.web.server import WebRuntime, make_handler


class PiWebTests(unittest.TestCase):
    def test_missing_snapshot_never_invents_normal_or_online(self):
        with tempfile.TemporaryDirectory() as directory:
            status = RuntimeStatusAdapter(Path(directory)).status()
        self.assertFalse(status["snapshot_available"])
        self.assertEqual(status["mode"], "waiting")
        self.assertIsNone(status["camera_online"])
        self.assertIsNone(status["vision_risk"])
        self.assertIsNone(status["esp32_online"])
        self.assertIsNone(status["manual_alarm"])

    def test_snapshot_preserves_real_and_optional_esp32_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "latest_status.json").write_text(json.dumps({
                "mode": "live", "published_at_monotonic": time.monotonic(), "camera_online": True, "total_people": 6,
                "vision_risk": "CROWD", "crowd_index": 0.27, "esp32_online": True,
                "mq2_value": 568, "mq2_phase": "READY", "mq2_warning": False,
                "temperature_c": 28.5, "humidity_percent": 57.2, "manual_alarm": True,
                "manual_alarm_remaining_ms": 18000, "manual_alarm_source": "现场按钮",
                "esp32_system_state": "CROWD", "recommended_direction": "LEFT",
            }), encoding="utf-8")
            status = RuntimeStatusAdapter(root).status()
        self.assertTrue(status["snapshot_available"])
        self.assertEqual(status["mq2_phase"], "READY")
        self.assertEqual(status["manual_alarm_remaining_ms"], 18000)
        self.assertEqual(status["recommended_direction"], "LEFT")

    def test_stale_snapshot_is_not_presented_as_live_camera_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "latest_status.json").write_text(json.dumps({
                "mode": "live", "published_at_monotonic": time.monotonic() - 10,
                "camera_online": True, "total_people": 9, "vision_risk": "CROWD",
            }), encoding="utf-8")
            status = RuntimeStatusAdapter(root, max_age_seconds=1.0).status()
        self.assertEqual(status["mode"], "stale")
        self.assertFalse(status["snapshot_available"])
        self.assertFalse(status["camera_online"])
        self.assertIsNone(status["total_people"])

    def test_display_script_uses_a_valid_arrow_iife_terminator(self):
        script = (Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "display.js").read_text(encoding="utf-8")
        self.assertTrue(script.rstrip().endswith("})();"))
        self.assertFalse(script.rstrip().endswith("}());"))
    def test_http_api_display_redirect_and_range_video_work_without_hardware_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            showcase = root / "showcase_videos"
            showcase.mkdir()
            (showcase / "case.mp4").write_bytes(b"0123456789")
            from http.server import ThreadingHTTPServer
            runtime = WebRuntime(root, showcase)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(runtime))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                status = json.loads(urlopen(base + "/api/status", timeout=1).read())
                self.assertFalse(status["snapshot_available"])
                self.assertIn("showcase-video", urlopen(base + "/teacher", timeout=1).read().decode("utf-8"))
                self.assertIn("showcase-video", urlopen(base + "/display", timeout=1).read().decode("utf-8"))
                self.assertIn("HuianApi", urlopen(base + "/static/js/api.js", timeout=1).read().decode("utf-8"))
                read_only_post = Request(
                    base + "/api/vision", data=b"{}", headers={"Content-Type": "application/json"}, method="POST",
                )
                with self.assertRaises(HTTPError) as raised:
                    urlopen(read_only_post, timeout=1)
                self.assertEqual(raised.exception.code, 404)
                showcases = json.loads(urlopen(base + "/api/showcases", timeout=1).read())
                self.assertEqual(showcases["videos"][0]["id"], "case.mp4")
                range_request = Request(base + "/showcase/case.mp4", headers={"Range": "bytes=2-5"})
                with urlopen(range_request, timeout=1) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.headers["Content-Range"], "bytes 2-5/10")
                    self.assertEqual(response.read(), b"2345")

                class NoRedirect(HTTPRedirectHandler):
                    def redirect_request(self, *_args, **_kwargs):
                        return None

                with self.assertRaises(HTTPError) as raised:
                    build_opener(NoRedirect).open(base + "/teacher", timeout=1)
                self.assertEqual(raised.exception.code, 302)
                self.assertEqual(raised.exception.headers["Location"], "/display")
            finally:
                server.shutdown()
                server.server_close()

if __name__ == "__main__":
    unittest.main()