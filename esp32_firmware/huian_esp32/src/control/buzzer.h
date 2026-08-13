#pragma once

#include "../decision/fire_engine.h"

class Buzzer {
 public:
  void begin();
  void update(SystemState state, unsigned long now);
  void updatePersonLinkTest(bool visionValid, int totalPeople, bool receivedVisionUpdate,
                            unsigned long now);

 private:
  void setEnabled(bool enabled);
  bool personTestPulseActive_ = false;
  unsigned long personTestPulseStartedMs_ = 0;
};