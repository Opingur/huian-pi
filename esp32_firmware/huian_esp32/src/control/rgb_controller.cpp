#include "rgb_controller.h"

#include <Arduino.h>
#include "../config.h"

void RgbController::begin() {
  pinMode(LEFT_RGB_R_PIN, OUTPUT);
  pinMode(LEFT_RGB_G_PIN, OUTPUT);
  pinMode(LEFT_RGB_B_PIN, OUTPUT);

  pinMode(RIGHT_RGB_R_PIN, OUTPUT);
  pinMode(RIGHT_RGB_G_PIN, OUTPUT);
  pinMode(RIGHT_RGB_B_PIN, OUTPUT);

  setBothColors(false, false, false);
}

void RgbController::setBothColors(bool red, bool green, bool blue) {
  digitalWrite(LEFT_RGB_R_PIN, red);
  digitalWrite(LEFT_RGB_G_PIN, green);
  digitalWrite(LEFT_RGB_B_PIN, blue);

  digitalWrite(RIGHT_RGB_R_PIN, red);
  digitalWrite(RIGHT_RGB_G_PIN, green);
  digitalWrite(RIGHT_RGB_B_PIN, blue);
}

void RgbController::update(SystemState state, unsigned long now) {

  // 正常：绿色常亮
  if (state == SYSTEM_NORMAL) {
    setBothColors(false, true, false);
  }

  // 拥挤预警：蓝色常亮
  else if (state == CROWD_WARNING) {
    setBothColors(false, false, true);
  }

  // 拥挤危险：黄色闪烁
  else if (state == CROWD_DANGER) {
    const bool on =
        (now / CROWD_DANGER_BLINK_INTERVAL_MS) % 2 == 0;

    // 红 + 绿 = 黄
    setBothColors(on, on, false);
  }

  // 火警：红色快速闪烁
  // 系统最高级报警
  else if (state == FIRE_EMERGENCY) {
    const bool on =
        (now / FIRE_BLINK_INTERVAL_MS) % 2 == 0;

    setBothColors(on, false, false);
  }

  // 通信异常：紫色慢闪
  else if (state == COMM_TIMEOUT) {
    const bool on =
        (now / COMM_TIMEOUT_BLINK_INTERVAL_MS) % 2 == 0;

    // 红 + 蓝 = 紫
    setBothColors(on, false, on);
  }

  else {
    setBothColors(false, false, false);
  }
}

void RgbController::updatePersonLinkTest(
    bool visionValid,
    int totalPeople,
    unsigned long now) {

  if (!visionValid) {
    update(COMM_TIMEOUT, now);
  }

  else if (totalPeople >= 1) {
    // 临时 Person Link 测试模式
    setBothColors(true, false, false);
  }

  else {
    setBothColors(false, true, false);
  }
}