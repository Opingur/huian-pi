#pragma once

#include <Arduino.h>
#include "sensors/smoke_sensor.h"
#include "sensors/temperature_sensor.h"

struct VisionState {
  String risk = "NORMAL";
  float crowdIndex = 0.0f;
  int totalPeople = 0;
  bool conflict = false;
  bool fireSuspected = false;
  bool smokeSuspected = false;
  float fireConfidence = 0.0f;
  float smokeConfidence = 0.0f;
  unsigned long lastUpdateMs = 0;
  bool valid = false;
};

bool updateVisionStateFromUart(HardwareSerial& uart, VisionState& state);
bool parseVisionJson(const String& line, VisionState& state);
void expireVisionStateIfStale(VisionState& state, unsigned long now);

// Sends ESP32-owned runtime state on Serial2 as one newline-delimited JSON object.
void sendEsp32Status(HardwareSerial& uart, const VisionState& vision,
                     const SmokeState& smoke, const TemperatureState& temperature,
                     const char* systemState);