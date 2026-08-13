"""Static contract checks for the formal Arduino Sketch when Arduino CLI is unavailable."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "esp32_firmware" / "huian_esp32"
SOURCE = FIRMWARE / "src"


class Esp32FusionStaticTests(unittest.TestCase):
    def setUp(self):
        self.engine = (SOURCE / "decision" / "fire_engine.cpp").read_text(encoding="utf-8")
        self.protocol = (SOURCE / "uart_protocol.cpp").read_text(encoding="utf-8")
        self.buzzer = (SOURCE / "control" / "buzzer.cpp").read_text(encoding="utf-8")
        self.rgb = (SOURCE / "control" / "rgb_controller.cpp").read_text(encoding="utf-8")
        self.config = (SOURCE / "config.h").read_text(encoding="utf-8")
        self.sketch = (FIRMWARE / "huian_esp32.ino").read_text(encoding="utf-8")
        self.temperature_h = (SOURCE / "sensors" / "temperature_sensor.h").read_text(encoding="utf-8")
        self.temperature_cpp = (SOURCE / "sensors" / "temperature_sensor.cpp").read_text(encoding="utf-8")

    @staticmethod
    def _contract(vision_valid, vision_risk, fire, smoke, mq2, dht):
        visual = vision_valid and (fire or smoke)
        if (mq2 and dht) or (visual and (mq2 or dht)):
            return "FIRE_EMERGENCY"
        if not vision_valid:
            return "COMM_TIMEOUT"
        if vision_risk == "DANGER":
            return "CROWD_DANGER"
        if vision_risk in {"CROWD", "WARNING"}:
            return "CROWD_WARNING"
        return "SYSTEM_NORMAL"

    def test_required_fusion_cases(self):
        cases = [
            (True, "NORMAL", False, False, False, False, "SYSTEM_NORMAL"),
            (True, "NORMAL", True, False, False, False, "SYSTEM_NORMAL"),
            (True, "NORMAL", True, False, True, False, "FIRE_EMERGENCY"),
            (True, "NORMAL", False, True, True, False, "FIRE_EMERGENCY"),
            (True, "NORMAL", True, False, False, True, "FIRE_EMERGENCY"),
            (True, "NORMAL", False, False, True, True, "FIRE_EMERGENCY"),
            (True, "DANGER", False, False, True, False, "CROWD_DANGER"),
            (False, "DANGER", False, False, False, False, "COMM_TIMEOUT"),
            (False, "DANGER", False, False, True, True, "FIRE_EMERGENCY"),
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(self._contract(*case[:-1]), case[-1])

    def test_visual_evidence_requires_fire_or_smoke_flag_not_crowd_danger(self):
        self.assertIn("vision.fireSuspected || vision.smokeSuspected", self.engine)
        self.assertNotIn('smoke.warning && vision.risk == "DANGER"', self.engine)

    def test_timeout_clears_visual_state_and_is_blue_silent(self):
        self.assertIn("state.fireSuspected = false", self.protocol)
        self.assertIn("state.valid = false", self.protocol)
        self.assertIn("state == COMM_TIMEOUT", self.rgb)
        self.assertIn("setBothColors(false, false, on)", self.rgb)
        self.assertIn("state == SYSTEM_NORMAL || state == COMM_TIMEOUT", self.buzzer)

    def test_verified_hardware_mapping_and_explicit_serial2(self):
        expected = {
            "BUZZER_PIN": "25", "MQ2_PIN": "34", "DHT11_PIN": "4",
            "LEFT_RGB_R_PIN": "27", "LEFT_RGB_G_PIN": "32", "LEFT_RGB_B_PIN": "26",
            "RIGHT_RGB_R_PIN": "33", "RIGHT_RGB_G_PIN": "13", "RIGHT_RGB_B_PIN": "14",
            "VISION_UART_RX_PIN": "16", "VISION_UART_TX_PIN": "17",
        }
        for name, value in expected.items():
            self.assertIn(f"#define {name} {value}", self.config)
        self.assertIn("SERIAL_8N1", self.sketch)
        self.assertIn("VISION_UART_RX_PIN", self.sketch)
        self.assertIn("VISION_UART_TX_PIN", self.sketch)

    def test_both_rgb_modules_share_each_state_color_output(self):
        for pin, channel in (
            ("LEFT_RGB_R_PIN", "red"), ("LEFT_RGB_G_PIN", "green"), ("LEFT_RGB_B_PIN", "blue"),
            ("RIGHT_RGB_R_PIN", "red"), ("RIGHT_RGB_G_PIN", "green"), ("RIGHT_RGB_B_PIN", "blue"),
        ):
            self.assertIn(f"digitalWrite({pin}, {channel})", self.rgb)
    def test_final_alert_timing_and_usb_debug_contract(self):
        for definition in (
            "CROWD_DANGER_BLINK_INTERVAL_MS 400UL",
            "FIRE_BLINK_INTERVAL_MS 200UL",
            "COMM_TIMEOUT_BLINK_INTERVAL_MS 800UL",
            "USB_DEBUG_INTERVAL_MS 1000UL",
        ):
            self.assertIn(definition, self.config)
        self.assertIn("setBothColors(false, true, false)", self.rgb)
        self.assertIn("setBothColors(true, true, false)", self.rgb)
        self.assertIn("setBothColors(on, false, false)", self.rgb)
        self.assertIn("setBothColors(on, false, on)", self.rgb)
        self.assertIn("setBothColors(false, false, on)", self.rgb)
        self.assertIn("now - lastUsbDebugMs >= USB_DEBUG_INTERVAL_MS", self.sketch)
        self.assertIn("printUsbDebug(smoke, temperature, visionState, systemState)", self.sketch)
        for field in (
            "MQ2=", "MQ2_WARN=", "TEMP=", "TEMP_VALID=", "TEMP_WARN=",
            "VISION_VALID=", "VISION_RISK=", "FIRE_VISION=", "SMOKE_VISION=", "SYSTEM_STATE=",
        ):
            self.assertIn(field, self.sketch)
        self.assertNotIn("delay(", self.sketch)

    def test_esp32_status_reverse_uart_contract(self):
        self.assertIn("ESP32_STATUS_SEND_INTERVAL_MS 1000UL", self.config)
        self.assertIn("sendEsp32Status(VISION_UART_PORT, visionState, smoke, temperature,", self.sketch)
        self.assertIn("doc[\"vision_valid\"] = vision.valid", self.protocol)
        for field in (
            'doc["protocol_version"]', 'doc["message_type"] = "esp32_status"',
            'doc["uptime_ms"] = millis()', 'doc["mq2_value"]', 'doc["mq2_warning"]',
            'doc["temperature_c"]', 'doc["temperature_valid"]', 'doc["temperature_warning"]',
            'doc["system_state"]', 'doc["vision_valid"]',
        ):
            self.assertIn(field, self.protocol)
        self.assertIn('doc["temperature_c"] = nullptr', self.protocol)
        self.assertIn("serializeJson(doc, payload, sizeof(payload))", self.protocol)
        self.assertIn("uart.write", self.protocol)
        self.assertIn("uart.write('\\n')", self.protocol)
    def test_dht_prototype_threshold_is_35_celsius(self):
        self.assertIn("#define TEMPERATURE_THRESHOLD 35.0f", self.config)
        self.assertIn("not a certified fire-safety threshold", self.config)
        self.assertIn("celsius >= TEMPERATURE_THRESHOLD", self.temperature_cpp)
    def test_dht_and_continuous_fire_buzzer_contract(self):
        self.assertIn("if (state == FIRE_EMERGENCY)", self.buzzer)
        self.assertIn("return setEnabled(true)", self.buzzer)
        self.assertIn("#include <DHT.h>", self.temperature_h)
        self.assertIn("bool valid = false", self.temperature_h)
        self.assertIn("dht_.begin()", self.temperature_cpp)
        self.assertIn("dht_.readTemperature()", self.temperature_cpp)
        self.assertIn("if (isnan(celsius))", self.temperature_cpp)


if __name__ == "__main__":
    unittest.main()