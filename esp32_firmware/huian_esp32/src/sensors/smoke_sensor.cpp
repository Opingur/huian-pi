#include "smoke_sensor.h"

#include "../config.h"

void SmokeSensor::begin() {
  pinMode(MQ2_PIN, INPUT);
}

void SmokeSensor::updateWarningState(int value) {
  if (!warning_) {
    lowCount_ = 0;
    if (value >= MQ2_TRIGGER_THRESHOLD) {
      if (highCount_ < MQ2_CONFIRM_SAMPLES) ++highCount_;
      if (highCount_ >= MQ2_CONFIRM_SAMPLES) {
        warning_ = true;
        highCount_ = 0;
      }
    } else {
      highCount_ = 0;
    }
    return;
  }

  highCount_ = 0;
  if (value <= MQ2_RELEASE_THRESHOLD) {
    if (lowCount_ < MQ2_RELEASE_SAMPLES) ++lowCount_;
    if (lowCount_ >= MQ2_RELEASE_SAMPLES) {
      warning_ = false;
      lowCount_ = 0;
    }
  } else {
    // In the hysteresis band (120 < ADC < 200), retain the confirmed warning.
    lowCount_ = 0;
  }
}

SmokeState SmokeSensor::read() {
  const unsigned long now = millis();
  if (!hasSample_ || now - lastSampleMs_ >= MQ2_SAMPLE_INTERVAL_MS) {
    value_ = analogRead(MQ2_PIN);
    updateWarningState(value_);
    lastSampleMs_ = now;
    hasSample_ = true;
  }

  SmokeState state;
  state.value = value_;
  state.warning = warning_;
  state.highCount = highCount_;
  state.lowCount = lowCount_;
  return state;
}