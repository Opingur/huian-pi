#include "buzzer.h"

#include <Arduino.h>
#include "../config.h"

void Buzzer::begin() {
  pinMode(BUZZER_PIN, OUTPUT);
  setEnabled(false);
}

void Buzzer::setEnabled(bool enabled) {
  digitalWrite(BUZZER_PIN, enabled);
}

void Buzzer::update(SystemState state, unsigned long now) {
  if (state == SYSTEM_NORMAL || state == COMM_TIMEOUT) {
    return setEnabled(false);
  }
  if (state == FIRE_EMERGENCY) {
    return setEnabled(true);
  }
  const unsigned long interval = state == CROWD_DANGER
      ? BUZZER_FAST_INTERVAL_MS
      : BUZZER_SLOW_INTERVAL_MS;
  setEnabled((now / interval) % 2 == 0);
}
void Buzzer::updatePersonLinkTest(bool visionValid, int totalPeople,
                                  bool receivedVisionUpdate, unsigned long now) {
  if (!visionValid || totalPeople < 1) {
    personTestPulseActive_ = false;
    return setEnabled(false);
  }
  if (receivedVisionUpdate) {
    personTestPulseActive_ = true;
    personTestPulseStartedMs_ = now;
  }
  if (personTestPulseActive_ && now - personTestPulseStartedMs_ < PERSON_LINK_BEEP_DURATION_MS) {
    return setEnabled(true);
  }
  personTestPulseActive_ = false;
  setEnabled(false);
}