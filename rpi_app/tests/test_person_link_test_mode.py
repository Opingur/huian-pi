"""Static and behavioral contract checks for the temporary person UART test mode."""

import unittest
from pathlib import Path

from communication.esp32 import UART_FIELDS
from tools.person_uart_integration_test import build_person_test_status


ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "esp32_firmware" / "huian_esp32"
SOURCE = FIRMWARE / "src"


class PersonLinkReference:
    """Small behavioral model of the compile-time test branch only."""

    def __init__(self):
        self.pulse_started = None

    def update(self, valid, total_people, received_update, now_ms):
        if not valid:
            self.pulse_started = None
            return "BLUE", False
        if total_people < 1:
            self.pulse_started = None
            return "GREEN", False
        if received_update:
            self.pulse_started = now_ms
        active = self.pulse_started is not None and now_ms - self.pulse_started < 150
        return "RED", active


class PersonLinkTestModeTests(unittest.TestCase):
    def setUp(self):
        self.config = (SOURCE / "config.h").read_text(encoding="utf-8")
        self.sketch = (FIRMWARE / "huian_esp32.ino").read_text(encoding="utf-8")
        self.rgb = (SOURCE / "control" / "rgb_controller.cpp").read_text(encoding="utf-8")
        self.buzzer = (SOURCE / "control" / "buzzer.cpp").read_text(encoding="utf-8")

    def test_mode_zero_keeps_formal_actuator_calls(self):
        self.assertIn("#define PERSON_LINK_TEST_MODE 0", self.config)
        self.assertIn("#if PERSON_LINK_TEST_MODE", self.sketch)
        self.assertIn("#else\n  rgbController.update(systemState, now);\n  buzzer.update(systemState, now);", self.sketch)

    def test_person_protocol_payload_has_all_required_fields(self):
        payload = build_person_test_status(2)
        self.assertEqual(tuple(payload), UART_FIELDS)
        self.assertEqual(payload["total_people"], 2)
        self.assertEqual(payload["vision_risk"], "NORMAL")
        self.assertFalse(payload["vision_fire_suspected"])

    def test_zero_people_is_green_and_silent(self):
        runtime = PersonLinkReference()
        self.assertEqual(runtime.update(True, 0, True, 0), ("GREEN", False))

    def test_one_or_more_people_is_red_with_new_short_beep(self):
        for people in (1, 5):
            with self.subTest(people=people):
                runtime = PersonLinkReference()
                self.assertEqual(runtime.update(True, people, True, 0), ("RED", True))

    def test_returning_to_zero_is_green_and_silent(self):
        runtime = PersonLinkReference()
        runtime.update(True, 1, True, 0)
        self.assertEqual(runtime.update(True, 0, True, 10), ("GREEN", False))

    def test_beep_is_nonblocking_150ms_pulse(self):
        runtime = PersonLinkReference()
        self.assertEqual(runtime.update(True, 1, True, 0), ("RED", True))
        self.assertEqual(runtime.update(True, 1, False, 149), ("RED", True))
        self.assertEqual(runtime.update(True, 1, False, 150), ("RED", False))
        self.assertIn("PERSON_LINK_BEEP_DURATION_MS 150UL", self.config)
        self.assertIn("now - personTestPulseStartedMs_ < PERSON_LINK_BEEP_DURATION_MS", self.buzzer)
        self.assertNotIn("delay(", self.buzzer)

    def test_uart_timeout_is_blue_and_silent(self):
        runtime = PersonLinkReference()
        runtime.update(True, 1, True, 0)
        self.assertEqual(runtime.update(False, 1, False, 10), ("BLUE", False))
        self.assertIn("update(COMM_TIMEOUT, now)", self.rgb)
        self.assertIn("if (!visionValid || totalPeople < 1)", self.buzzer)


if __name__ == "__main__":
    unittest.main()