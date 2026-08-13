#pragma once

#include <Arduino.h>

struct SmokeState {
  int value = 0;
  bool warning = false;
  unsigned int highCount = 0;
  unsigned int lowCount = 0;
};

class SmokeSensor {
 public:
  void begin();
  SmokeState read();

 private:
  int value_ = 0;
  bool warning_ = false;
  unsigned int highCount_ = 0;
  unsigned int lowCount_ = 0;
  unsigned long lastSampleMs_ = 0;
  bool hasSample_ = false;

  void updateWarningState(int value);
};