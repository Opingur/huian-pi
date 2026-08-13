#pragma once

#include "../decision/fire_engine.h"

class RgbController {
 public:
  void begin();
  void update(SystemState state, unsigned long now);
  void updatePersonLinkTest(bool visionValid, int totalPeople, unsigned long now);

 private:
  void setBothColors(bool red, bool green, bool blue);
};