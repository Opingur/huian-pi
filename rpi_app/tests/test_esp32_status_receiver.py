import json
import unittest

from communication.esp32 import ESP32Publisher, ESP32_STATUS_FIELDS, parse_esp32_status_message


class FakeSerial:
    def __init__(self, incoming=b""):
        self.incoming = bytearray(incoming)
        self.closed = False

    @property
    def in_waiting(self):
        return len(self.incoming)

    def read(self, size):
        data = bytes(self.incoming[:size])
        del self.incoming[:size]
        return data

    def close(self):
        self.closed = True


def status_payload(**overrides):
    payload = {
        "protocol_version": 1,
        "message_type": "esp32_status",
        "uptime_ms": 1200,
        "mq2_value": 250,
        "mq2_warning": True,
        "temperature_c": 36.5,
        "temperature_valid": True,
        "temperature_warning": True,
        "system_state": "FIRE",
        "vision_valid": True,
    }
    payload.update(overrides)
    return payload


class Esp32StatusReceiverTests(unittest.TestCase):
    def test_valid_status_contains_all_required_real_fields(self):
        payload = status_payload()
        parsed = parse_esp32_status_message(json.dumps(payload), received_at=10.0)
        self.assertIsNotNone(parsed)
        self.assertEqual(set(payload), set(ESP32_STATUS_FIELDS))
        self.assertEqual(parsed.system_state, "FIRE")
        self.assertEqual(parsed.temperature_c, 36.5)
        self.assertEqual(parsed.received_at, 10.0)

    def test_warning_crowd_and_danger_states_are_accepted(self):
        for system_state in ("WARNING", "CROWD", "DANGER"):
            with self.subTest(system_state=system_state):
                parsed = parse_esp32_status_message(
                    json.dumps(status_payload(system_state=system_state)),
                    received_at=10.0,
                )
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed.system_state, system_state)

    def test_invalid_temperature_never_becomes_a_fake_number(self):
        valid_invalid = status_payload(temperature_c=None, temperature_valid=False, temperature_warning=False)
        parsed = parse_esp32_status_message(json.dumps(valid_invalid), received_at=1.0)
        self.assertIsNotNone(parsed)
        self.assertIsNone(parsed.temperature_c)
        fake_temperature = status_payload(temperature_c=0.0, temperature_valid=False, temperature_warning=False)
        self.assertIsNone(parse_esp32_status_message(json.dumps(fake_temperature)))

    def test_optional_web_status_fields_are_preserved_without_changing_uart_schema(self):
        parsed = parse_esp32_status_message(json.dumps(status_payload(
            mq2_phase="READY", mq2_baseline=587, humidity_percent=57.2,
            manual_alarm=True, manual_alarm_remaining_ms=18000,
            manual_alarm_source="button", recommended_direction="LEFT",
            left_exit_state="CROWD", right_exit_state="NORMAL", arrow_direction="RIGHT",
            unknown_future_field={"not": "a scalar"},
        )))
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.extras["mq2_phase"], "READY")
        self.assertEqual(parsed.extras["mq2_baseline"], 587)
        self.assertTrue(parsed.extras["manual_alarm"])
        self.assertEqual(parsed.extras["arrow_direction"], "RIGHT")
        self.assertNotIn("unknown_future_field", parsed.extras)

    def test_bad_or_wrong_direction_json_is_ignored(self):
        self.assertIsNone(parse_esp32_status_message("not-json"))
        self.assertIsNone(parse_esp32_status_message(json.dumps(status_payload(message_type="vision_status"))))
        incomplete = status_payload()
        del incomplete["vision_valid"]
        self.assertIsNone(parse_esp32_status_message(json.dumps(incomplete)))

    def test_partial_lines_buffer_until_newline_then_parse(self):
        message = (json.dumps(status_payload(), separators=(",", ":")) + "\n").encode("utf-8")
        publisher = ESP32Publisher({"enabled": True, "dry_run": False, "port": "/dev/test", "status_timeout_seconds": 3.0})
        serial = FakeSerial(message[:17])
        publisher._serial = serial
        self.assertIsNone(publisher.poll_esp32_status(now=4.0))
        serial.incoming.extend(message[17:])
        parsed = publisher.poll_esp32_status(now=5.0)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.mq2_value, 250)
        self.assertFalse(publisher.esp32_status_is_stale(now=7.9))
        self.assertTrue(publisher.esp32_status_is_stale(now=8.1))

    def test_malformed_complete_line_does_not_stop_later_valid_line(self):
        valid = json.dumps(status_payload(system_state="CROWD_DANGER")) + "\n"
        publisher = ESP32Publisher({"enabled": True, "dry_run": False, "port": "/dev/test"})
        publisher._serial = FakeSerial(b'{bad}\n' + valid.encode("utf-8"))
        parsed = publisher.poll_esp32_status(now=9.0)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.system_state, "CROWD_DANGER")


if __name__ == "__main__":
    unittest.main()