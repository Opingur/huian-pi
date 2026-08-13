#include "temperature_sensor.h"

#include <math.h>
#include "../config.h"

void TemperatureSensor::begin() {
  dht_.begin();
}

TemperatureState TemperatureSensor::read() {
  TemperatureState state;
  const float celsius = dht_.readTemperature();
  if (isnan(celsius)) {
    return state;
  }
  state.celsius = celsius;
  state.valid = true;
  state.warning = celsius >= TEMPERATURE_THRESHOLD;
  return state;
}