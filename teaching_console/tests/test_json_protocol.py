from __future__ import annotations

import unittest

from teaching_console.services.json_protocol import (
    PI_PAYLOAD_FIELDS, build_pi_payload, classroom_case_expected_response, encode_uart_message,
    parse_esp32_status, validate_pi_payload,
)


class JsonProtocolTests(unittest.TestCase):
    def test_pi_payload_is_complete_and_smoke_is_formal_default(self) -> None:
        payload = build_pi_payload({"vision_risk": "DANGER", "vision_smoke_suspected": True})
        self.assertEqual(tuple(payload), PI_PAYLOAD_FIELDS)
        self.assertFalse(payload["vision_smoke_suspected"])
        self.assertEqual(payload["vision_smoke_confidence"], 0.0)
        self.assertEqual(validate_pi_payload(payload), (True, "Pi 协议字段完整。"))

    def test_uart_message_is_one_utf8_json_line(self) -> None:
        encoded = encode_uart_message('{"protocol_version":1,"vision_risk":"NORMAL"}')
        self.assertTrue(encoded.endswith(b"\n"))
        self.assertNotIn(b"\n", encoded[:-1])

    def test_classroom_case_responses_use_final_semantics(self) -> None:
        self.assertIn("绿灯", classroom_case_expected_response("NORMAL"))
        self.assertIn("蓝灯", classroom_case_expected_response("WARNING"))
        self.assertIn("黄灯", classroom_case_expected_response("CROWD"))
        self.assertIn("火警", classroom_case_expected_response("DANGER"))
        self.assertIn("持续", classroom_case_expected_response("DANGER"))

    def test_status_json_parses_and_debug_text_is_ignored(self) -> None:
        status = '{"protocol_version":1,"message_type":"esp32_status","uptime_ms":1,"mq2_value":10,"mq2_warning":false,"temperature_c":null,"temperature_valid":false,"temperature_warning":false,"system_state":"NORMAL","vision_valid":true}'
        self.assertEqual(parse_esp32_status(status)["mq2_value"], 10)
        self.assertIsNone(parse_esp32_status("========== HUAIAN STATUS =========="))
        self.assertIsNone(parse_esp32_status("not json"))


if __name__ == "__main__":
    unittest.main()
