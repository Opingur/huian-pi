#include "fire_engine.h"

SystemState evaluateSystemState(
    const VisionState& vision,
    const SmokeState& smoke,
    const TemperatureState& temperature) {

  // ------------------------------------------------------------
  // 1. 视觉火灾证据
  //
  // 这里只认 Fire/Smoke YOLO 的火焰或烟雾检测结果。
  // 人群拥堵 DANGER 不能被误认为火灾。
  // ------------------------------------------------------------
  const bool visualFireEvidence =
      vision.valid &&
      (vision.fireSuspected || vision.smokeSuspected);


  // ------------------------------------------------------------
  // 2. ESP32 本地传感器证据
  // ------------------------------------------------------------
  const bool smokeAlarm =
      smoke.warning;

  const bool temperatureAlarm =
      temperature.valid &&
      temperature.warning;


  // ------------------------------------------------------------
  // 3. 系统状态优先级
  //
  // FIRE 最高优先级。
  //
  // 重要安全兜底：
  // 即使树莓派掉线，只要 MQ-2 已经经过连续确认并进入 warning，
  // ESP32 也必须能够独立进入 FIRE_EMERGENCY。
  // 不能让 COMM_TIMEOUT 把烟雾报警压住。
  // ------------------------------------------------------------

  // MQ-2 本地烟雾报警可以独立触发 FIRE。
  if (smokeAlarm) {
    return FIRE_EMERGENCY;
  }


  // 视觉检测到火焰/烟雾，同时本地温度异常，
  // 两种不同来源证据融合后进入 FIRE。
  if (visualFireEvidence && temperatureAlarm) {
    return FIRE_EMERGENCY;
  }


  // ------------------------------------------------------------
  // 4. 树莓派通信异常
  //
  // 只有在没有 FIRE 的情况下，
  // 通信超时才进入 COMM_TIMEOUT。
  // ------------------------------------------------------------
  if (!vision.valid) {
    return COMM_TIMEOUT;
  }


  // ------------------------------------------------------------
  // 5. 人群拥堵状态
  // ------------------------------------------------------------
  if (vision.risk == "DANGER") {
    return CROWD_DANGER;
  }

  if (vision.risk == "CROWD" ||
      vision.risk == "WARNING") {
    return CROWD_WARNING;
  }


  // ------------------------------------------------------------
  // 6. 正常状态
  // ------------------------------------------------------------
  return SYSTEM_NORMAL;
}