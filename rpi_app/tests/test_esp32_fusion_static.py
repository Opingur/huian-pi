"""Static contracts for the current, single-file formal ESP32 firmware.

Arduino CLI is not available in the Windows regression environment, so these
checks protect the verified `.ino` protocol and state-machine boundaries.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKETCH = ROOT / "esp32_firmware" / "huian_esp32" / "huian_esp32.ino"


def _source() -> str:
    return SKETCH.read_text(encoding="utf-8")


def test_formal_state_parser_and_rank_keep_crowd_separate_from_fire():
    sketch = _source()
    assert 'state == "CROWD" || state == "CROWDED" || state == "CROWD_WARNING" || state == "CROWD_DANGER"' in sketch
    assert 'if (state == "DANGER") return RouteState::DANGER;' in sketch
    assert 'if (state == "FIRE" || state == "FIRE_EMERGENCY") return RouteState::FIRE;' in sketch
    for state, rank in (("NORMAL", 0), ("WARNING", 1), ("CROWD", 2), ("DANGER", 3), ("FIRE", 4)):
        assert f"case RouteState::{state}: return {rank};" in sketch
    assert 'case RouteState::CROWD: return "CROWD";' in sketch


def test_verified_hardware_mapping_and_serial2_remain_explicit():
    sketch = _source()
    for declaration in (
        "constexpr uint8_t LEFT_R = 32;", "constexpr uint8_t LEFT_G = 26;", "constexpr uint8_t LEFT_B = 27;",
        "constexpr uint8_t RIGHT_R = 13;", "constexpr uint8_t RIGHT_G = 14;", "constexpr uint8_t RIGHT_B = 33;",
        "constexpr uint8_t BUZZER_PIN = 25;", "constexpr uint8_t MQ2_PIN = 34;", "constexpr uint8_t DHT_PIN = 4;",
        "constexpr uint8_t PI_RX_PIN = 16;", "constexpr uint8_t PI_TX_PIN = 17;",
    ):
        assert declaration in sketch
    assert "HardwareSerial PiSerial(2);" in sketch
    assert "PiSerial.begin(" in sketch and "SERIAL_8N1" in sketch


def test_current_buzzer_and_timeout_semantics_are_present():
    sketch = _source()
    assert "enum class BuzzerMode" in sketch
    for mode in ("SILENT", "WARNING", "CROWD", "RUNNING", "FIRE"):
        assert f"BuzzerMode::{mode}" in sketch
    assert "case BuzzerMode::WARNING: on = (elapsed % 2200UL) < 180UL;" in sketch
    assert "case BuzzerMode::CROWD: on = (elapsed % 300UL) < 150UL;" in sketch
    assert "case BuzzerMode::RUNNING: on = (elapsed % 2000UL) < 80UL;" in sketch
    assert "case BuzzerMode::FIRE: on = true;" in sketch
    assert "VISION_TIMEOUT_MS = 5000UL" in sketch
    assert "showCommunicationOffline();" in sketch
    assert "setLeft(true, false, true);" in sketch and "setRight(true, false, true);" in sketch


def test_status_json_is_mirrored_to_pi_uart_and_usb_serial():
    sketch = _source()
    for field in (
        'reply["protocol_version"]', 'reply["message_type"]', 'reply["uptime_ms"]',
        'reply["mq2_value"]', 'reply["mq2_warning"]', 'reply["temperature_c"]',
        'reply["temperature_valid"]', 'reply["temperature_warning"]', 'reply["system_state"]',
        'reply["vision_valid"]',
    ):
        assert field in sketch
    assert "serializeJson(" in sketch
    assert "reply,\n    PiSerial" in sketch and "reply,\n    Serial" in sketch
    assert "PiSerial.write(" in sketch and "Serial.write(" in sketch


def test_running_event_is_auxiliary_and_does_not_override_formal_alerts():
    sketch = _source()
    assert "vision.runningEvent =" in sketch and "doc[\"running_event\"]" in sketch
    assert "vision.runningCount =" in sketch and "doc[\"running_count\"]" in sketch
    assert "return vision.runningEvent ? BuzzerMode::RUNNING : BuzzerMode::SILENT;" in sketch
    assert "case RouteState::CROWD: return BuzzerMode::CROWD;" in sketch