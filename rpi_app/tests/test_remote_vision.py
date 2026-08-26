import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from communication.remote_vision import RemoteVisionServer, SourceArbitratingPublisher, validate_remote_status


class _FakePublisher:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.enabled = True
        self.dry_run = True

    def send_status(self, status, *, source_timestamp=None):
        self.sent.append((dict(status), source_timestamp))
        return True

    def poll_esp32_status(self, *, now=None):
        return None

    def esp32_status_is_stale(self, *, now=None):
        return True

    def reset_send_interval(self):
        return None

    def close(self):
        self.closed = True


def _status(**changes):
    payload = {
        "vision_risk": "CROWD", "crowd_index": 0.42, "total_people": 12,
        "recommended_direction": "RIGHT", "left_exit_count": 8, "right_exit_count": 4,
    }
    payload.update(changes)
    return payload


class RemoteVisionTests(unittest.TestCase):
    def test_validation_rejects_out_of_range_or_unknown_commands(self):
        accepted = validate_remote_status(_status())
        self.assertEqual(accepted["vision_risk"], "CROWD")
        with self.assertRaisesRegex(ValueError, "crowd_index"):
            validate_remote_status(_status(crowd_index=1.2))
        with self.assertRaisesRegex(ValueError, "recommended_direction"):
            validate_remote_status(_status(recommended_direction="UP"))

    def test_remote_lease_suppresses_local_sends_then_releases(self):
        now = [10.0]
        serial = _FakePublisher()
        publisher = SourceArbitratingPublisher(serial, remote_lease_seconds=3.0, clock=lambda: now[0])
        self.assertTrue(publisher.send_remote_status(validate_remote_status(_status())))
        self.assertFalse(publisher.send_status(_status(vision_risk="NORMAL")))
        now[0] = 13.1
        self.assertTrue(publisher.send_status(_status(vision_risk="NORMAL")))
        self.assertTrue(publisher.release_remote())
        self.assertEqual(serial.sent[-1][0]["vision_risk"], "NORMAL")

    def test_http_listener_is_authenticated_and_never_opens_another_uart(self):
        serial = _FakePublisher()
        publisher = SourceArbitratingPublisher(serial)
        server = RemoteVisionServer(publisher, "secret", host="127.0.0.1", port=0)
        server.start()
        try:
            base = f"http://127.0.0.1:{server._server.server_port}/api/vision"
            body = json.dumps(_status()).encode("utf-8")
            request = Request(base, data=body, headers={"Content-Type": "application/json", "X-Huian-Bridge-Key": "secret"}, method="POST")
            self.assertTrue(json.loads(urlopen(request, timeout=1).read())["ok"])
            self.assertEqual(len(serial.sent), 1)
            denied = Request(base, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with self.assertRaises(HTTPError) as raised:
                urlopen(denied, timeout=1)
            self.assertEqual(raised.exception.code, 401)
            release = Request(base + "/release", data=b"{}", headers={"X-Huian-Bridge-Key": "secret"}, method="POST")
            self.assertTrue(json.loads(urlopen(release, timeout=1).read())["ok"])
            self.assertFalse(serial.closed)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()