import json
import sys
import unittest
from unittest.mock import patch

from communication.esp32 import ESP32Publisher, UART_FIELDS, build_uart_payload, encode_uart_message


class Esp32PublisherTests(unittest.TestCase):
    def setUp(self):
        self.status = {
            "protocol_version": 1, "timestamp": 123, "vision_risk": "DANGER", "crowd_index": 0.83,
            "total_people": 16, "direction_conflict": True,
            "vision_fire_suspected": True, "vision_smoke_suspected": False,
            "vision_fire_confidence": 0.82, "vision_smoke_confidence": 0.0,
            "bbox": [1, 2, 3, 4], "flow_groups": [{"id": 1}], "predicted_people_10s": 20,
        }

    def test_payload_contains_only_protocol_fields(self):
        self.assertEqual(tuple(build_uart_payload(self.status)), UART_FIELDS)
        self.assertNotIn("bbox", build_uart_payload(self.status))

    def test_message_is_compact_json_with_one_newline(self):
        message = encode_uart_message(self.status)
        self.assertTrue(message.endswith(b"\n"))
        self.assertEqual(message.count(b"\n"), 1)
        self.assertEqual(json.loads(message), build_uart_payload(self.status))

    def test_dry_run_never_imports_pyserial(self):
        publisher = ESP32Publisher({"enabled": True, "dry_run": True})
        with patch.dict(sys.modules, {"serial": None}):
            self.assertTrue(publisher.send_status(self.status, source_timestamp=0.0))
        publisher.close()

    def test_disabled_never_imports_or_opens_serial(self):
        publisher = ESP32Publisher({"enabled": False, "dry_run": False})
        with patch.dict(sys.modules, {"serial": None}):
            self.assertFalse(publisher.send_status(self.status, source_timestamp=0.0))
        publisher.close()

    def test_missing_real_port_is_clear(self):
        publisher = ESP32Publisher({"enabled": True, "dry_run": False, "port": ""})
        with self.assertRaisesRegex(RuntimeError, "serial port is not configured"):
            publisher.send_status(self.status, source_timestamp=0.0)

    def test_fire_state_encodes_while_visual_smoke_compatibility_is_fixed_off(self):
        for suspected in (False, True):
            status = dict(self.status, vision_fire_suspected=suspected, vision_smoke_suspected=True, vision_smoke_confidence=0.91)
            payload = build_uart_payload(status)
            self.assertEqual(payload["vision_fire_suspected"], suspected)
            self.assertFalse(payload["vision_smoke_suspected"])
            self.assertEqual(payload["vision_smoke_confidence"], 0.0)

    def test_interval_limits_repeated_video_or_camera_snapshots(self):
        publisher = ESP32Publisher({"enabled": True, "dry_run": True, "send_interval_seconds": 1.0})
        self.assertTrue(publisher.send_status(self.status, source_timestamp=0.0))
        self.assertFalse(publisher.send_status(self.status, source_timestamp=0.5))
        self.assertTrue(publisher.send_status(self.status, source_timestamp=1.0))


if __name__ == "__main__":
    unittest.main()