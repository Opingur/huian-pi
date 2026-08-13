#include "uart_protocol.h"

#include <ArduinoJson.h>
#include "config.h"

namespace {
constexpr size_t kMaxUartLineLength = 511;

bool hasRequiredFields(const JsonDocument& doc) {
  return doc.containsKey("protocol_version") && doc.containsKey("timestamp") &&
         doc.containsKey("vision_risk") && doc.containsKey("crowd_index") &&
         doc.containsKey("total_people") && doc.containsKey("direction_conflict") &&
         doc.containsKey("vision_fire_suspected") && doc.containsKey("vision_smoke_suspected") &&
         doc.containsKey("vision_fire_confidence") && doc.containsKey("vision_smoke_confidence");
}

void clearVisionEvidence(VisionState& state) {
  state.risk = "NORMAL";
  state.crowdIndex = 0.0f;
  state.totalPeople = 0;
  state.conflict = false;
  state.fireSuspected = false;
  state.smokeSuspected = false;
  state.fireConfidence = 0.0f;
  state.smokeConfidence = 0.0f;
}
}  // namespace

bool parseVisionJson(const String& line, VisionState& state) {
  StaticJsonDocument<512> doc;
  if (deserializeJson(doc, line) || !hasRequiredFields(doc)) return false;
  if ((doc["protocol_version"] | 0) != UART_PROTOCOL_VERSION) return false;

  const char* risk = doc["vision_risk"] | "NORMAL";
  state.risk = String(risk);
  state.crowdIndex = doc["crowd_index"] | 0.0f;
  state.totalPeople = doc["total_people"] | 0;
  state.conflict = doc["direction_conflict"] | false;
  state.fireSuspected = doc["vision_fire_suspected"] | false;
  state.smokeSuspected = doc["vision_smoke_suspected"] | false;
  state.fireConfidence = doc["vision_fire_confidence"] | 0.0f;
  state.smokeConfidence = doc["vision_smoke_confidence"] | 0.0f;
  state.lastUpdateMs = millis();
  state.valid = true;
  return true;
}

void expireVisionStateIfStale(VisionState& state, unsigned long now) {
  if (state.valid && now - state.lastUpdateMs > VISION_UART_TIMEOUT_MS) {
    clearVisionEvidence(state);
    state.valid = false;
  }
}

bool updateVisionStateFromUart(HardwareSerial& uart, VisionState& state) {
  static String line;
  bool updated = false;
  while (uart.available()) {
    const char incoming = static_cast<char>(uart.read());
    if (incoming == '\n') {
      if (line.length()) updated = parseVisionJson(line, state) || updated;
      line = "";
    } else if (incoming != '\r' && line.length() < kMaxUartLineLength) {
      line += incoming;
    } else if (line.length() >= kMaxUartLineLength) {
      line = "";
    }
  }
  return updated;
}
void sendEsp32Status(HardwareSerial& uart, const VisionState& vision,
                     const SmokeState& smoke, const TemperatureState& temperature,
                     const char* systemState) {
  StaticJsonDocument<512> doc;
  doc["protocol_version"] = UART_PROTOCOL_VERSION;
  doc["message_type"] = "esp32_status";
  doc["uptime_ms"] = millis();
  doc["mq2_value"] = smoke.value;
  doc["mq2_warning"] = smoke.warning;
  if (temperature.valid) {
    doc["temperature_c"] = temperature.celsius;
  } else {
    // No synthetic temperature is reported when DHT11 has no valid measurement.
    doc["temperature_c"] = nullptr;
  }
  doc["temperature_valid"] = temperature.valid;
  doc["temperature_warning"] = temperature.warning;
  doc["system_state"] = systemState;
  doc["vision_valid"] = vision.valid;
  
  char payload[384];
  size_t length = serializeJson(doc, payload, sizeof(payload));

  uart.write(
      reinterpret_cast<const uint8_t*>(payload),
      length
  );
  uart.write('\n');
}