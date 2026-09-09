import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from communication.esp32 import Esp32Status
from communication.remote_vision import RemoteVisionServer, SourceArbitratingPublisher, validate_remote_status


class _FakePublisher:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.enabled = True
        self.dry_run = True
        self.esp32_status = Esp32Status(protocol_version=1, uptime_ms=1200, mq2_value=314, mq2_warning=False, temperature_c=28.6, temperature_valid=True, temperature_warning=False, system_state="NORMAL", vision_valid=True, received_at=1.0)

    def send_status(self, status, *, source_timestamp=None):
        self.sent.append((dict(status), source_timestamp))
        return True

    def poll_esp32_status(self, *, now=None):
        return self.esp32_status

    def esp32_status_is_stale(self, *, now=None):
        return True

    def reset_send_interval(self):
        return None

    def close(self):
        self.closed = True


class _IntervalFakePublisher(_FakePublisher):
    """Model the ESP32 publisher interval to protect alert transitions."""

    def __init__(self):
        super().__init__()
        self._last_sent_at = None

    def send_status(self, status, *, source_timestamp=None):
        if self._last_sent_at is not None and source_timestamp - self._last_sent_at < 1.0:
            return False
        self.sent.append((dict(status), source_timestamp))
        self._last_sent_at = source_timestamp
        return True

    def reset_send_interval(self):
        self._last_sent_at = None

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


    def test_remote_risk_transition_bypasses_uart_interval_once(self):
        now = [10.0]
        serial = _IntervalFakePublisher()
        publisher = SourceArbitratingPublisher(serial, remote_lease_seconds=3.0, clock=lambda: now[0])
        self.assertTrue(publisher.send_remote_status(validate_remote_status(_status(vision_risk="NORMAL"))))
        # This is intentionally at the same instant: an ordinary UART throttle
        # would suppress it, but an alert transition must not wait a second.
        self.assertTrue(publisher.send_remote_status(validate_remote_status(_status(vision_risk="CROWD"))))
        self.assertEqual([entry[0]["vision_risk"] for entry in serial.sent], ["NORMAL", "CROWD"])
    def test_http_listener_is_authenticated_and_never_opens_another_uart(self):
        serial = _FakePublisher()
        publisher = SourceArbitratingPublisher(serial)
        server = RemoteVisionServer(publisher, "secret", host="127.0.0.1", port=0)
        server.start()
        try:
            base = f"http://127.0.0.1:{server._server.server_port}/api/vision"
            body = json.dumps(_status()).encode("utf-8")
            request = Request(base, data=body, headers={"Content-Type": "application/json", "X-Huian-Bridge-Key": "secret"}, method="POST")
            reply = json.loads(urlopen(request, timeout=1).read())
            self.assertTrue(reply["ok"])
            self.assertEqual(reply["esp32_status"]["mq2_value"], 314)
            self.assertEqual(reply["esp32_status"]["temperature_c"], 28.6)
            self.assertEqual(reply["esp32_status"]["system_state"], "NORMAL")
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