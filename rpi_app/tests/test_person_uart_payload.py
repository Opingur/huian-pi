"""Regression coverage for the manual Pi person-to-UART helper payload."""

from tools.person_uart_integration_test import build_person_test_status
from communication.esp32 import UART_FIELDS


def test_manual_person_uart_payload_matches_the_formal_protocol():
    payload = build_person_test_status(2)
    assert tuple(payload) == UART_FIELDS
    assert payload["total_people"] == 2
    assert payload["vision_risk"] == "NORMAL"
    assert payload["running_event"] is False
    assert payload["running_count"] == 0