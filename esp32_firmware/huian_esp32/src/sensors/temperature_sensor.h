#pragma once

#include <DHT.h>
#include "../config.h"

struct TemperatureState {
  float celsius = 0.0f;
  bool warning = false;
  bool valid = false;
};

class TemperatureSensor {
 public:
  void begin();
  TemperatureState read();

 private:
  DHT dht_{DHT11_PIN, DHT11};
};