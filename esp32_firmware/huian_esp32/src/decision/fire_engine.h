#pragma once

#include "../uart_protocol.h"
#include "../sensors/smoke_sensor.h"
#include "../sensors/temperature_sensor.h"

enum SystemState { SYSTEM_NORMAL, CROWD_WARNING, CROWD_DANGER, COMM_TIMEOUT, FIRE_EMERGENCY };

SystemState evaluateSystemState(const VisionState& vision, const SmokeState& smoke,
                                const TemperatureState& temperature);