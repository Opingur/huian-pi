"""Boundary tests for the configured MQ-2 hysteresis and confirmation contract."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SMOKE_CPP = ROOT / "esp32_firmware" / "huian_esp32" / "src" / "sensors" / "smoke_sensor.cpp"
CONFIG_H = ROOT / "esp32_firmware" / "huian_esp32" / "src" / "config.h"


class ReferenceMq2StateMachine:
    trigger = 200
    release = 120
    confirm_samples = 3
    release_samples = 3

    def __init__(self):
        self.warning = False
        self.high = 0
        self.low = 0

    def sample(self, value: int) -> bool:
        if not self.warning:
            self.low = 0
            if value >= self.trigger:
                self.high = min(self.high + 1, self.confirm_samples)
                if self.high >= self.confirm_samples:
                    self.warning = True
                    self.high = 0
            else:
                self.high = 0
        else:
            self.high = 0
            if value <= self.release:
                self.low = min(self.low + 1, self.release_samples)
                if self.low >= self.release_samples:
                    self.warning = False
                    self.low = 0
            else:
                self.low = 0
        return self.warning


class Mq2StateMachineTests(unittest.TestCase):
    def assert_sequence(self, values, expected):
        machine = ReferenceMq2StateMachine()
        actual = [machine.sample(value) for value in values]
        self.assertEqual(actual, expected)

    def test_boundaries_and_confirmation(self):
        self.assert_sequence([199, 199, 199], [False, False, False])
        self.assert_sequence([200, 200], [False, False])
        self.assert_sequence([200, 200, 200], [False, False, True])
        self.assert_sequence([0, 0, 500, 0], [False, False, False, False])

    def test_hysteresis_and_release_confirmation(self):
        machine = ReferenceMq2StateMachine()
        for value in (200, 200, 200):
            machine.sample(value)
        self.assertTrue(machine.warning)
        for value in (150, 150, 150, 120, 120):
            self.assertTrue(machine.sample(value))
        self.assertFalse(machine.sample(120))

    def test_formal_source_uses_cached_500ms_state_machine(self):
        config = CONFIG_H.read_text(encoding="utf-8")
        source = SMOKE_CPP.read_text(encoding="utf-8")
        for definition in (
            "MQ2_TRIGGER_THRESHOLD 200", "MQ2_RELEASE_THRESHOLD 120",
            "MQ2_CONFIRM_SAMPLES 3", "MQ2_RELEASE_SAMPLES 3", "MQ2_SAMPLE_INTERVAL_MS 500UL",
        ):
            self.assertIn(definition, config)
        self.assertNotIn("SMOKE_THRESHOLD", config)
        self.assertIn("now - lastSampleMs_ >= MQ2_SAMPLE_INTERVAL_MS", source)
        self.assertIn("value >= MQ2_TRIGGER_THRESHOLD", source)
        self.assertIn("value <= MQ2_RELEASE_THRESHOLD", source)
        self.assertIn("updateWarningState(value_)", source)
        self.assertNotIn("delay(", source)


if __name__ == "__main__":
    unittest.main()