/*
  ==========================================================
  慧安楼道安全监测系统 - ESP32 成品综合主程序
  版本：2026-08-12 FINAL TEST

  功能：
  1. Raspberry Pi 5 -> UART JSON -> ESP32
  2. MQ-2 烟雾检测
  3. DHT11 温湿度检测
  4. 双 RGB 状态指示
  5. 有源蜂鸣器报警
  6. 环境火情融合
  7. ESP32 -> Raspberry Pi 状态回传
  8. PS2 摇杆 SW 一键人工报警
  9. 双 MAX7219 左右楼梯口分流箭头

  依赖：
  - DHT sensor library
  - Adafruit Unified Sensor
  - ArduinoJson 7

  当前测试阈值：
  MQ-2 触发：300
  MQ-2 解除：120
  温度：35.0 ℃

  最终状态语义：
  NORMAL：绿灯常亮；蜂鸣器静音。
  WARNING：蓝灯 600ms 慢闪；每约2.2秒短鸣一次。
  CROWD / DANGER：黄灯 250ms 快速闪烁；对应蜂鸣器节奏不变。
  FIRE：独立确认火情内部状态；红灯 200ms 快速闪烁；蜂鸣器持续长鸣。
  COMM_TIMEOUT：状态上报为通信超时；灯保持正常绿色，蜂鸣器静音。
  PS2 一键报警：紫灯 120ms 快速闪烁；80ms 响 / 80ms 停，20 秒后自动恢复。

  注意：
  上述阈值用于当前演示测试，
  不是正式消防阈值。
  ==========================================================
*/

#include <Arduino.h>
#include <DHT.h>
#include <ArduinoJson.h>


// ==========================================================
// 1. 成品最终 GPIO 映射
// ==========================================================

// RGB 实测映射（逐 GPIO 点亮确认）
// 左侧：D27 = 红，D32 = 绿，D26 = 蓝。
constexpr uint8_t LEFT_R = 27;
constexpr uint8_t LEFT_G = 32;
constexpr uint8_t LEFT_B = 26;

// 右侧：D33 = 红，D13 = 绿，D14 = 蓝。
constexpr uint8_t RIGHT_R = 33;
constexpr uint8_t RIGHT_G = 13;
constexpr uint8_t RIGHT_B = 14;

// 蜂鸣器
constexpr uint8_t BUZZER_PIN = 25;

// MQ-2
constexpr uint8_t MQ2_PIN = 34;

// DHT11
constexpr uint8_t DHT_PIN = 4;
#define DHT_TYPE DHT11

// UART2
constexpr uint8_t PI_RX_PIN = 16;   // Pi TX -> ESP32 RX
constexpr uint8_t PI_TX_PIN = 17;   // Pi RX <- ESP32 TX

// PS2 摇杆：仅使用 SW 按键；INPUT_PULLUP，按下为 LOW。
constexpr uint8_t MANUAL_ALARM_SW_PIN = 22;

// 两块级联 MAX7219 8x8 点阵：DIN=21，CLK=18，CS=19。
constexpr uint8_t MAX7219_DIN_PIN = 21;
constexpr uint8_t MAX7219_CLK_PIN = 18;
constexpr uint8_t MAX7219_CS_PIN = 19;
constexpr uint8_t MAX7219_DEVICE_COUNT = 2;
constexpr uint8_t MAX7219_INTENSITY = 3;
constexpr uint8_t MAX7219_LEFT_DEVICE = 0;
constexpr uint8_t MAX7219_RIGHT_DEVICE = 1;


// ==========================================================
// 2. 通信与采样参数
// ==========================================================

constexpr uint32_t BAUD = 115200;

constexpr uint32_t VISION_TIMEOUT_MS = 5000UL;

constexpr uint32_t MQ2_INTERVAL_MS = 500UL;
constexpr uint32_t MQ2_WARMUP_MS = 120000UL;
constexpr uint32_t MQ2_CALIBRATION_MS = 30000UL;
constexpr uint32_t MQ2_STABLE_BASELINE_WINDOW_MS = 30000UL;
constexpr uint16_t MQ2_STABLE_STEP_MAX = 10;
constexpr uint16_t MQ2_CALIBRATION_SPREAD_MAX = 30;
constexpr uint32_t DHT_INTERVAL_MS = 2500UL;
constexpr uint32_t REPORT_INTERVAL_MS = 1000UL;

constexpr uint32_t BUTTON_DEBOUNCE_MS = 40UL;
constexpr uint32_t MANUAL_ALARM_DURATION_MS = 20000UL;
constexpr uint32_t MANUAL_ALARM_RGB_BLINK_MS = 120UL;
constexpr uint32_t MANUAL_ALARM_BUZZER_HALF_PERIOD_MS = 80UL;


// ==========================================================
// 3. 当前演示测试阈值
// ==========================================================

// MQ-2 uses a clean-air baseline. A normal warning needs about six seconds
// of continuous abnormal readings; an exceptionally strong reading stays fast.
constexpr uint16_t MQ2_TRIGGER_MIN_DELTA = 200;
constexpr uint8_t MQ2_TRIGGER_PERCENT = 25;
constexpr uint16_t MQ2_RELEASE_MIN_DELTA = 80;
constexpr uint8_t MQ2_RELEASE_PERCENT = 10;
constexpr uint16_t MQ2_SEVERE_MIN_DELTA = 600;
constexpr uint8_t MQ2_SEVERE_PERCENT = 75;

constexpr uint8_t MQ2_CONFIRM_SAMPLES = 12;
constexpr uint8_t MQ2_SEVERE_CONFIRM_SAMPLES = 3;
constexpr uint8_t MQ2_RELEASE_SAMPLES = 10;

// DHT11 is an environmental display-only warning; it cannot trigger FIRE.
constexpr float TEMP_WARNING_THRESHOLD_C = 35.0F;


// ==========================================================
// 4. 状态定义
// ==========================================================

enum class RouteState : uint8_t {
  NORMAL,
  WARNING,
  CROWD,
  DANGER,
  FIRE
};


enum class BuzzerMode : uint8_t {
  SILENT,
  WARNING,
  CROWD,
  RUNNING,
  MANUAL_ALARM,
  FIRE
};


// ==========================================================
// 5. 树莓派视觉数据
// ==========================================================

enum class ArrowDirection : uint8_t {
  NONE,
  LEFT,
  RIGHT
};

enum class ArrowMode : uint8_t {
  OFF,
  LEFT_ONLY,
  RIGHT_ONLY,
  LEFT_FLASH,
  RIGHT_FLASH,
  BOTH_STEADY,
  BOTH_FLASH
};


// ==========================================================

struct VisionData {

  // Global visual risk is presented on both RGB units. Side risks only add
  // a lateral evacuation indication after Pi has real horizontal-flow proof.
  RouteState global = RouteState::NORMAL;
  RouteState left = RouteState::NORMAL;
  RouteState right = RouteState::NORMAL;

  int leftCount = 0;
  int rightCount = 0;
  int totalCount = 0;

  float crowdIndex = 0.0F;

  bool conflict = false;

  // Auxiliary event: never changes the formal route/fire state.
  bool runningEvent = false;
  int runningCount = 0;

  bool fireSuspected = false;
  bool smokeSuspected = false;

  float fireConfidence = 0.0F;
  float smokeConfidence = 0.0F;

  bool fireConfirmed = false;
  // Paired exit-sign mode has priority. The legacy one-side direction remains
  // accepted only so an older Pi version cannot accidentally light both signs.
  ArrowDirection recommendedDirection = ArrowDirection::NONE;
  bool recommendedDirectionProvided = false;
  ArrowMode arrowMode = ArrowMode::OFF;
  bool arrowModeProvided = false;

  uint32_t lastRxMs = 0;

  bool valid = false;
};


// ==========================================================
// 6. ESP32 本地传感器数据
// ==========================================================

struct SensorData {

  uint16_t mq2Raw = 0;
  uint16_t mq2Baseline = 0;
  uint16_t mq2TriggerThreshold = 0;
  uint16_t mq2ReleaseThreshold = 0;
  uint16_t mq2SevereThreshold = 0;

  bool mq2Ready = false;
  uint32_t mq2StableSinceMs = 0;
  uint32_t mq2CalibrationStartedMs = 0;
  uint32_t mq2CalibrationSum = 0;
  uint16_t mq2CalibrationMin = 4095;
  uint16_t mq2CalibrationMax = 0;
  uint16_t mq2CalibrationSamples = 0;
  uint16_t mq2LastStableRaw = 0;

  bool smokeWarning = false;

  uint8_t mq2HighCount = 0;
  uint8_t mq2LowCount = 0;

  float temperatureC = NAN;
  float humidity = NAN;

  bool dhtValid = false;

  bool tempHigh = false;
};


// ==========================================================
// 7. 对象与运行变量
// ==========================================================

DHT dht(DHT_PIN, DHT_TYPE);

HardwareSerial PiSerial(2);

VisionData vision;
SensorData sensors;

RouteState finalLeft = RouteState::NORMAL;
RouteState finalRight = RouteState::NORMAL;

bool fireEmergency = false;
bool communicationOffline = true;

String piBuffer;
String usbBuffer;

uint32_t lastMq2Ms = 0;
uint32_t lastDhtMs = 0;
uint32_t lastReportMs = 0;

BuzzerMode currentBuzzerMode = BuzzerMode::SILENT;
uint32_t buzzerModeStartMs = 0;

bool manualAlarm = false;
uint32_t manualAlarmStartMs = 0;
bool lastButtonReading = HIGH;
bool stableButtonState = HIGH;
uint32_t lastButtonChangeMs = 0;

ArrowMode currentArrowMode = ArrowMode::OFF;
bool currentMatrixVisible = false;

const byte ARROW_RIGHT[8] = {
  B00001000, B00001100, B00001110, B11111111,
  B11111111, B00001110, B00001100, B00001000
};
const byte ARROW_LEFT[8] = {
  B00010000, B00110000, B01110000, B11111111,
  B11111111, B01110000, B00110000, B00010000
};


// ==========================================================
// 8. 基础输出
// ==========================================================

void buzzerWrite(bool on) {

  digitalWrite(
    BUZZER_PIN,
    on ? HIGH : LOW
  );
}


void setLeft(bool r, bool g, bool b) {

  digitalWrite(
    LEFT_R,
    r ? HIGH : LOW
  );

  digitalWrite(
    LEFT_G,
    g ? HIGH : LOW
  );

  digitalWrite(
    LEFT_B,
    b ? HIGH : LOW
  );
}


void setRight(bool r, bool g, bool b) {

  digitalWrite(
    RIGHT_R,
    r ? HIGH : LOW
  );

  digitalWrite(
    RIGHT_G,
    g ? HIGH : LOW
  );

  digitalWrite(
    RIGHT_B,
    b ? HIGH : LOW
  );
}


// ==========================================================
// 9. 状态文字
// ==========================================================

const char* stateText(RouteState state) {

  switch (state) {

    case RouteState::NORMAL:
      return "NORMAL";

    case RouteState::WARNING:
      return "WARNING";

    case RouteState::CROWD:
      return "CROWD";


    case RouteState::DANGER:
      return "DANGER";

    case RouteState::FIRE:
      return "FIRE";
  }

  return "NORMAL";
}


// ==========================================================
// 10. 树莓派风险字符串 -> ESP32 状态
// ==========================================================

RouteState parseState(const char* raw) {
  if (!raw) return RouteState::NORMAL;

  String state(raw);
  state.trim();
  state.toUpperCase();

  if (state == "NORMAL" || state == "CLEAR") return RouteState::NORMAL;
  if (state == "WARNING" || state == "ATTENTION") return RouteState::WARNING;
  if (state == "CROWD" || state == "CROWDED" || state == "CROWD_WARNING" || state == "CROWD_DANGER") return RouteState::CROWD;
  if (state == "DANGER") return RouteState::DANGER;
  if (state == "FIRE" || state == "FIRE_EMERGENCY") return RouteState::FIRE;
  return RouteState::NORMAL;
}


// ==========================================================
// 11. 风险等级
// ==========================================================

int stateRank(RouteState state) {
  switch (state) {
    case RouteState::NORMAL: return 0;
    case RouteState::WARNING: return 1;
    case RouteState::CROWD: return 2;
    case RouteState::DANGER: return 3;
    case RouteState::FIRE: return 4;
  }
  return 0;
}


RouteState maxState(
  RouteState a,
  RouteState b
) {

  if (
    stateRank(a) >=
    stateRank(b)
  ) {

    return a;
  }

  return b;
}


// ==========================================================
// 12. 综合状态
// ==========================================================

const char* overallSystemState() {
  if (fireEmergency) return "FIRE";
  if (communicationOffline) return "COMM_TIMEOUT";

  switch (maxState(finalLeft, finalRight)) {
    case RouteState::NORMAL: return "NORMAL";
    case RouteState::WARNING: return "WARNING";
    case RouteState::CROWD: return "CROWD";
    case RouteState::DANGER: return "DANGER";
    case RouteState::FIRE: return "FIRE";
  }
  return "NORMAL";
}


// ==========================================================
// 13. RGB 闪烁节奏
// ==========================================================

bool stateBlinkOn(
  RouteState state,
  uint32_t now
) {
  switch (state) {
    case RouteState::NORMAL:
      return true;
    case RouteState::WARNING:
      return ((now / 600UL) % 2UL) == 0UL;
    case RouteState::CROWD:
      return ((now / 250UL) % 2UL) == 0UL;
    case RouteState::DANGER:
    case RouteState::FIRE:
      return ((now / 200UL) % 2UL) == 0UL;
  }
  return true;
}


// ==========================================================
// 14. 左 RGB
// ==========================================================

void showLeftState(RouteState state) {
  if (!stateBlinkOn(state, millis())) {
    setLeft(false, false, false);
    return;
  }

  switch (state) {
    case RouteState::NORMAL: setLeft(false, true, false); return;
    case RouteState::WARNING: setLeft(false, false, true); return;
    case RouteState::CROWD: setLeft(true, true, false); return;
    case RouteState::DANGER: setLeft(true, false, false); return;
    case RouteState::FIRE: setLeft(true, false, false); return;
  }
}


// ==========================================================
// 15. 右 RGB
// ==========================================================

void showRightState(RouteState state) {
  if (!stateBlinkOn(state, millis())) {
    setRight(false, false, false);
    return;
  }

  switch (state) {
    case RouteState::NORMAL: setRight(false, true, false); return;
    case RouteState::WARNING: setRight(false, false, true); return;
    case RouteState::CROWD: setRight(true, true, false); return;
    case RouteState::DANGER: setRight(true, false, false); return;
    case RouteState::FIRE: setRight(true, false, false); return;
  }
}


// ==========================================================
// 16. 树莓派离线显示
// 紫色闪烁 + 蜂鸣器静音
// ==========================================================

void showCommunicationOffline() {

  uint32_t now = millis();

  bool visible =
    ((now / 350UL) % 2UL) == 0UL;

  if (!visible) {

    setLeft(false, false, false);
    setRight(false, false, false);

    return;
  }

  // 紫色 = 红 + 蓝
  setLeft(true, false, true);
  setRight(true, false, true);
}


// ==========================================================
// 17. 解析 Raspberry Pi -> ESP32 JSON
// ==========================================================

ArrowDirection parseArrowDirection(const char* raw) {
  if (!raw) return ArrowDirection::NONE;
  String value(raw); value.trim(); value.toUpperCase();
  if (value == "LEFT" || value == "L") return ArrowDirection::LEFT;
  if (value == "RIGHT" || value == "R") return ArrowDirection::RIGHT;
  return ArrowDirection::NONE;
}

ArrowMode parseArrowMode(const char* raw) {
  if (!raw) return ArrowMode::OFF;
  String value(raw); value.trim(); value.toUpperCase();
  if (value == "BOTH_STEADY") return ArrowMode::BOTH_STEADY;
  if (value == "BOTH_FLASH") return ArrowMode::BOTH_FLASH;
  if (value == "LEFT_ONLY") return ArrowMode::LEFT_ONLY;
  if (value == "RIGHT_ONLY") return ArrowMode::RIGHT_ONLY;
  if (value == "LEFT_FLASH") return ArrowMode::LEFT_FLASH;
  if (value == "RIGHT_FLASH") return ArrowMode::RIGHT_FLASH;
  return ArrowMode::OFF;
}

uint32_t manualAlarmRemainingMs() {
  if (!manualAlarm) return 0;
  const uint32_t elapsed = millis() - manualAlarmStartMs;
  return elapsed >= MANUAL_ALARM_DURATION_MS ? 0 : MANUAL_ALARM_DURATION_MS - elapsed;
}

void updateManualAlarmButton() {
  const bool reading = digitalRead(MANUAL_ALARM_SW_PIN);
  if (reading != lastButtonReading) {
    lastButtonChangeMs = millis();
    lastButtonReading = reading;
  }
  if (millis() - lastButtonChangeMs >= BUTTON_DEBOUNCE_MS && reading != stableButtonState) {
    stableButtonState = reading;
    if (stableButtonState == LOW) {
      manualAlarm = true;
      manualAlarmStartMs = millis();
      Serial.println("[MANUAL] PS2 button alarm started");
    }
  }
  if (manualAlarm && millis() - manualAlarmStartMs >= MANUAL_ALARM_DURATION_MS) {
    manualAlarm = false;
    Serial.println("[MANUAL] alarm finished");
  }
}

void showManualAlarm() {
  // PS2 一键报警是独立现场提示：紫色（红 + 蓝）快速闪烁。
  const bool visible = ((millis() / MANUAL_ALARM_RGB_BLINK_MS) % 2UL) == 0UL;
  setLeft(visible, false, visible);
  setRight(visible, false, visible);
}

constexpr uint8_t MAX7219_REG_DIGIT0 = 0x01;
constexpr uint8_t MAX7219_REG_DECODEMODE = 0x09;
constexpr uint8_t MAX7219_REG_INTENSITY = 0x0A;
constexpr uint8_t MAX7219_REG_SCANLIMIT = 0x0B;
constexpr uint8_t MAX7219_REG_SHUTDOWN = 0x0C;
constexpr uint8_t MAX7219_REG_DISPLAYTEST = 0x0F;

void max7219WriteAll(uint8_t reg, uint8_t value) {
  digitalWrite(MAX7219_CS_PIN, LOW);
  for (uint8_t device = 0; device < MAX7219_DEVICE_COUNT; ++device) {
    shiftOut(MAX7219_DIN_PIN, MAX7219_CLK_PIN, MSBFIRST, reg);
    shiftOut(MAX7219_DIN_PIN, MAX7219_CLK_PIN, MSBFIRST, value);
  }
  digitalWrite(MAX7219_CS_PIN, HIGH);
}

void max7219WriteDevice(uint8_t selectedDevice, uint8_t reg, uint8_t value) {
  digitalWrite(MAX7219_CS_PIN, LOW);
  for (uint8_t device = 0; device < MAX7219_DEVICE_COUNT; ++device) {
    shiftOut(MAX7219_DIN_PIN, MAX7219_CLK_PIN, MSBFIRST, reg);
    shiftOut(
      MAX7219_DIN_PIN,
      MAX7219_CLK_PIN,
      MSBFIRST,
      device == selectedDevice ? value : 0x00
    );
  }
  digitalWrite(MAX7219_CS_PIN, HIGH);
}

void clearMatrices() {
  for (uint8_t row = 0; row < 8; ++row) max7219WriteAll(MAX7219_REG_DIGIT0 + row, 0x00);
}

void drawArrowOnDevice(uint8_t device, const byte pattern[8]) {
  clearMatrices();
  for (uint8_t row = 0; row < 8; ++row) {
    max7219WriteDevice(device, MAX7219_REG_DIGIT0 + row, pattern[row]);
  }
}

void drawArrowPair(const byte leftPattern[8], const byte rightPattern[8]) {
  clearMatrices();
  for (uint8_t row = 0; row < 8; ++row) {
    digitalWrite(MAX7219_CS_PIN, LOW);
    for (uint8_t device = 0; device < MAX7219_DEVICE_COUNT; ++device) {
      shiftOut(MAX7219_DIN_PIN, MAX7219_CLK_PIN, MSBFIRST, MAX7219_REG_DIGIT0 + row);
      const byte value = device == MAX7219_LEFT_DEVICE ? leftPattern[row] : rightPattern[row];
      shiftOut(MAX7219_DIN_PIN, MAX7219_CLK_PIN, MSBFIRST, value);
    }
    digitalWrite(MAX7219_CS_PIN, HIGH);
  }
}

void initMatrices() {
  pinMode(MAX7219_DIN_PIN, OUTPUT);
  pinMode(MAX7219_CLK_PIN, OUTPUT);
  pinMode(MAX7219_CS_PIN, OUTPUT);
  digitalWrite(MAX7219_CS_PIN, HIGH);
  max7219WriteAll(MAX7219_REG_DECODEMODE, 0x00);
  max7219WriteAll(MAX7219_REG_SCANLIMIT, 0x07);
  max7219WriteAll(MAX7219_REG_INTENSITY, MAX7219_INTENSITY);
  max7219WriteAll(MAX7219_REG_DISPLAYTEST, 0x00);
  max7219WriteAll(MAX7219_REG_SHUTDOWN, 0x01);
  clearMatrices();
}


// ==========================================================

bool parseVisionJson(
  const String& line,
  const char* source
) {

  JsonDocument doc;

  DeserializationError err =
    deserializeJson(
      doc,
      line
    );


  if (err) {

    Serial.print(
      "[JSON ERROR] "
    );

    Serial.print(source);

    Serial.print(" : ");

    Serial.println(
      err.c_str()
    );

    return false;
  }


  // ---------- 协议版本 ----------

  int version =
    doc["protocol_version"] | 0;


  if (version != 1) {

    Serial.println(
      "[JSON ERROR] unsupported protocol_version"
    );

    return false;
  }


  // ---------- 全局视觉风险 ----------

  const char* globalRisk =
    doc["vision_risk"] | "NORMAL";

  vision.global = parseState(globalRisk);

  // 新字段指定“左/右出口”风险；保留旧字段兼容现有 JSON。
  const char* leftRisk = !doc["left_exit_risk"].isNull()
    ? (doc["left_exit_risk"] | globalRisk)
    : (doc["left_risk"] | globalRisk);
  const char* rightRisk = !doc["right_exit_risk"].isNull()
    ? (doc["right_exit_risk"] | globalRisk)
    : (doc["right_risk"] | globalRisk);

  vision.left = parseState(leftRisk);
  vision.right = parseState(rightRisk);

  // 双出口人数新字段优先，旧字段继续兼容。
  if (!doc["left_exit_count"].isNull()) {
    vision.leftCount = doc["left_exit_count"].as<int>();
  } else if (!doc["left_count"].isNull()) {
    vision.leftCount = doc["left_count"].as<int>();
  }
  if (!doc["right_exit_count"].isNull()) {
    vision.rightCount = doc["right_exit_count"].as<int>();
  } else if (!doc["right_count"].isNull()) {
    vision.rightCount = doc["right_count"].as<int>();
  }
  if (
    !doc["total_people"].isNull()
  ) {

    vision.totalCount =
      doc["total_people"].as<int>();

  } else {

    vision.totalCount =
      vision.leftCount +
      vision.rightCount;
  }


  // ---------- Crowd Index ----------

  if (
    !doc["crowd_index"].isNull()
  ) {

    vision.crowdIndex =
      doc["crowd_index"].as<float>();
  }


  // ---------- 人流冲突 ----------

  if (
    !doc["direction_conflict"].isNull()
  ) {

    vision.conflict =
      doc["direction_conflict"].as<bool>();
  }


  // ---------- 跑动辅助事件 ----------

  vision.runningEvent =
    doc["running_event"]
    | false;

  vision.runningCount =
    doc["running_count"]
    | 0;

  // ---------- 视觉火焰疑似 ----------

  vision.fireSuspected =
    doc["vision_fire_suspected"]
    | false;


  // ---------- 视觉烟雾疑似 ----------

  vision.smokeSuspected =
    doc["vision_smoke_suspected"]
    | false;


  // ---------- 置信度 ----------

  vision.fireConfidence =
    doc["vision_fire_confidence"]
    | 0.0F;

  vision.smokeConfidence =
    doc["vision_smoke_confidence"]
    | 0.0F;


  // ---------- 可选确认字段 ----------

  vision.fireConfirmed =
    doc["fire_confirmed"]
    | false;
  vision.recommendedDirectionProvided = !doc["recommended_direction"].isNull();
  vision.recommendedDirection = vision.recommendedDirectionProvided
    ? parseArrowDirection(doc["recommended_direction"] | "NONE")
    : ArrowDirection::NONE;
  vision.arrowModeProvided = !doc["arrow_mode"].isNull();
  vision.arrowMode = vision.arrowModeProvided
    ? parseArrowMode(doc["arrow_mode"] | "OFF")
    : ArrowMode::OFF;


  // ---------- UART 在线 ----------

  vision.lastRxMs =
    millis();

  vision.valid =
    true;


  Serial.print(
    "[PI] risk="
  );

  Serial.print(
    globalRisk
  );

  Serial.print(
    " people="
  );

  Serial.print(
    vision.totalCount
  );

  Serial.print(
    " crowd="
  );

  Serial.println(
    vision.crowdIndex,
    2
  );


  return true;
}


// ==========================================================
// 17. 按行读取 JSON
// ==========================================================

void readJsonStream(
  Stream& stream,
  String& buffer,
  const char* source
) {

  while (
    stream.available()
  ) {

    char c =
      static_cast<char>(
        stream.read()
      );


    if (c == '\r') {

      continue;
    }


    if (c == '\n') {

      buffer.trim();


      if (
        buffer.length() > 0
      ) {

        parseVisionJson(
          buffer,
          source
        );
      }


      buffer = "";

      continue;
    }


    // 防止异常数据无限增长

    if (
      buffer.length() >= 512
    ) {

      buffer = "";

      Serial.println(
        "[JSON ERROR] line too long"
      );

      continue;
    }


    buffer += c;
  }
}


// ==========================================================
// 18. MQ-2 ADC 平均值
// ==========================================================

uint16_t readMq2RawAverage() {

  constexpr uint8_t SAMPLE_COUNT = 30;

  uint32_t sum = 0;


  for (
    uint8_t i = 0;
    i < SAMPLE_COUNT;
    i++
  ) {

    sum +=
      analogRead(
        MQ2_PIN
      );

    delay(2);
  }


  return
    static_cast<uint16_t>(
      sum /
      SAMPLE_COUNT
    );
}


// ==========================================================
// 19. MQ-2 状态判断
// ==========================================================

void refreshMq2Thresholds() {

  sensors.mq2TriggerThreshold =
    sensors.mq2Baseline +
    max(
      MQ2_TRIGGER_MIN_DELTA,
      static_cast<uint16_t>(
        (static_cast<uint32_t>(sensors.mq2Baseline) * MQ2_TRIGGER_PERCENT) / 100UL
      )
    );

  sensors.mq2ReleaseThreshold =
    sensors.mq2Baseline +
    max(
      MQ2_RELEASE_MIN_DELTA,
      static_cast<uint16_t>(
        (static_cast<uint32_t>(sensors.mq2Baseline) * MQ2_RELEASE_PERCENT) / 100UL
      )
    );

  sensors.mq2SevereThreshold =
    sensors.mq2Baseline +
    max(
      MQ2_SEVERE_MIN_DELTA,
      static_cast<uint16_t>(
        (static_cast<uint32_t>(sensors.mq2Baseline) * MQ2_SEVERE_PERCENT) / 100UL
      )
    );
}

const char* mq2PhaseText() {
  if (millis() < MQ2_WARMUP_MS) return "WARMUP";
  if (!sensors.mq2Ready) return "CALIBRATING";
  return "READY";
}

uint32_t mq2WarmupRemainingMs() {
  const uint32_t elapsed = millis();
  return elapsed >= MQ2_WARMUP_MS ? 0UL : MQ2_WARMUP_MS - elapsed;
}

uint32_t mq2CalibrationRemainingMs() {
  if (sensors.mq2Ready) return 0UL;
  const uint32_t now = millis();
  if (now < MQ2_WARMUP_MS || sensors.mq2CalibrationStartedMs == 0UL) return MQ2_CALIBRATION_MS;
  const uint32_t elapsed = now - sensors.mq2CalibrationStartedMs;
  return elapsed >= MQ2_CALIBRATION_MS ? 0UL : MQ2_CALIBRATION_MS - elapsed;
}

void resetMq2Calibration(uint32_t now) {
  sensors.mq2CalibrationStartedMs = now;
  sensors.mq2CalibrationSum = 0;
  sensors.mq2CalibrationMin = 4095;
  sensors.mq2CalibrationMax = 0;
  sensors.mq2CalibrationSamples = 0;
}

void updateMq2State() {

  sensors.mq2Raw = readMq2RawAverage();
  const uint32_t now = millis();

  // The heater must settle before any calibration or alarm decision.
  if (now < MQ2_WARMUP_MS) {
    sensors.smokeWarning = false;
    sensors.mq2HighCount = 0;
    sensors.mq2LowCount = 0;
    sensors.mq2Ready = false;
    return;
  }

  // Build the initial baseline only from a continuous, low-variance clean-air window.
  if (!sensors.mq2Ready) {
    if (sensors.mq2CalibrationStartedMs == 0UL) resetMq2Calibration(now);

    sensors.mq2CalibrationSum += sensors.mq2Raw;
    sensors.mq2CalibrationMin = min(sensors.mq2CalibrationMin, sensors.mq2Raw);
    sensors.mq2CalibrationMax = max(sensors.mq2CalibrationMax, sensors.mq2Raw);
    sensors.mq2CalibrationSamples++;

    if (now - sensors.mq2CalibrationStartedMs >= MQ2_CALIBRATION_MS) {
      const uint16_t spread = sensors.mq2CalibrationMax - sensors.mq2CalibrationMin;
      if (sensors.mq2CalibrationSamples > 0 && spread <= MQ2_CALIBRATION_SPREAD_MAX) {
        sensors.mq2Baseline =
          static_cast<uint16_t>(sensors.mq2CalibrationSum / sensors.mq2CalibrationSamples);
        sensors.mq2Ready = true;
        sensors.mq2LastStableRaw = sensors.mq2Raw;
        sensors.mq2StableSinceMs = now;
        refreshMq2Thresholds();
      } else {
        // A changing environment is not a safe baseline: restart the clean-air window.
        resetMq2Calibration(now);
      }
    }
    return;
  }

  // Baseline may move only after a long, quiet and non-alarming period.
  const bool belowAlarmThreshold = sensors.mq2Raw < sensors.mq2TriggerThreshold;
  const uint16_t step =
    sensors.mq2Raw > sensors.mq2LastStableRaw
      ? sensors.mq2Raw - sensors.mq2LastStableRaw
      : sensors.mq2LastStableRaw - sensors.mq2Raw;
  if (!sensors.smokeWarning && belowAlarmThreshold && step <= MQ2_STABLE_STEP_MAX) {
    if (now - sensors.mq2StableSinceMs >= MQ2_STABLE_BASELINE_WINDOW_MS) {
      // Slow 25% correction prevents a transient rise from lifting today's threshold.
      sensors.mq2Baseline = static_cast<uint16_t>(
        (static_cast<uint32_t>(sensors.mq2Baseline) * 3UL + sensors.mq2Raw) / 4UL
      );
      refreshMq2Thresholds();
      sensors.mq2StableSinceMs = now;
    }
  } else {
    sensors.mq2StableSinceMs = now;
  }
  sensors.mq2LastStableRaw = sensors.mq2Raw;

  if (!sensors.smokeWarning) {
    sensors.mq2LowCount = 0;
    const bool severe = sensors.mq2Raw >= sensors.mq2SevereThreshold;
    const bool abnormal = sensors.mq2Raw >= sensors.mq2TriggerThreshold;
    if (abnormal) {
      if (sensors.mq2HighCount < MQ2_CONFIRM_SAMPLES) sensors.mq2HighCount++;
      const uint8_t required = severe ? MQ2_SEVERE_CONFIRM_SAMPLES : MQ2_CONFIRM_SAMPLES;
      if (sensors.mq2HighCount >= required) {
        sensors.smokeWarning = true;
        sensors.mq2HighCount = 0;
      }
    } else {
      sensors.mq2HighCount = 0;
    }
  } else {
    sensors.mq2HighCount = 0;
    if (sensors.mq2Raw <= sensors.mq2ReleaseThreshold) {
      if (sensors.mq2LowCount < MQ2_RELEASE_SAMPLES) sensors.mq2LowCount++;
      if (sensors.mq2LowCount >= MQ2_RELEASE_SAMPLES) {
        sensors.smokeWarning = false;
        sensors.mq2LowCount = 0;
        sensors.mq2StableSinceMs = now;
      }
    } else {
      sensors.mq2LowCount = 0;
    }
  }
}


// ==========================================================
// 20. 本地传感器更新
// ==========================================================

void updateSensors() {

  uint32_t now =
    millis();


  // ---------- MQ-2 ----------

  if (
    now - lastMq2Ms >=
    MQ2_INTERVAL_MS
  ) {

    lastMq2Ms =
      now;

    updateMq2State();
  }


  // ---------- DHT11 ----------

  if (
    now - lastDhtMs >=
    DHT_INTERVAL_MS
  ) {

    lastDhtMs =
      now;


    float humidity =
      dht.readHumidity();

    float temperature =
      dht.readTemperature();


    if (
      isnan(humidity) ||
      isnan(temperature)
    ) {

      sensors.dhtValid =
        false;

      sensors.tempHigh =
        false;

      Serial.println(
        "[DHT11] read failed"
      );

    } else {

      sensors.humidity =
        humidity;

      sensors.temperatureC =
        temperature;

      sensors.dhtValid =
        true;

      sensors.tempHigh =
        temperature >=
        TEMP_WARNING_THRESHOLD_C;
    }
  }
}


// ==========================================================
// 21. Pi UART 在线判断
// ==========================================================

bool piOnline() {

  if (
    !vision.valid
  ) {

    return false;
  }


  return (
    millis() -
    vision.lastRxMs
    <=
    VISION_TIMEOUT_MS
  );
}


// ==========================================================
// 22. 风险融合
// ==========================================================

void evaluateRisk() {

  bool online =
    piOnline();

  communicationOffline =
    !online;


  // ======================================================
  // 1. 在线时使用树莓派视觉风险
  //    离线时不再伪装成“正常”，
  //    而是由显示层进入紫色 COMM_TIMEOUT。
  // ======================================================

  if (online) {

    finalLeft =
      maxState(vision.global, vision.left);

    finalRight =
      maxState(vision.global, vision.right);

  } else {

    finalLeft =
      RouteState::NORMAL;

    finalRight =
      RouteState::NORMAL;
  }


  // FIRE requires two continuous and independent confirmations:
  // MQ-2 sustained smoke abnormality + Raspberry Pi visual fire confirmation.
  // Temperature remains an environmental display value, never a standalone fire trigger.
  const bool dualConfirmedFire =
    online &&
    sensors.mq2Ready &&
    sensors.smokeWarning &&
    vision.fireConfirmed;

  fireEmergency =
    dualConfirmedFire;

  // ======================================================
  // 4. 只有烟雾，没有达到 FIRE
  //    在线时显示黄色预警。
  //    离线时优先显示紫色通信异常。
  // ======================================================

  if (
    online &&
    sensors.smokeWarning &&
    !fireEmergency
  ) {

    finalLeft =
      maxState(
        finalLeft,
        RouteState::WARNING
      );

    finalRight =
      maxState(
        finalRight,
        RouteState::WARNING
      );
  }


  // ======================================================
  // 5. 视觉疑似火焰
  //    只在树莓派在线时生效。
  //    视觉烟雾字段仅为协议兼容，不再作为正式触发依据。
  // ======================================================

  if (
    online &&
    vision.fireSuspected &&
    !fireEmergency
  ) {

    finalLeft =
      maxState(
        finalLeft,
        RouteState::WARNING
      );

    finalRight =
      maxState(
        finalRight,
        RouteState::WARNING
      );
  }


  // ======================================================
  // 6. FIRE 最高优先级
  //
  // 红色闪烁 + 蜂鸣器持续报警
  // 覆盖树莓派离线紫灯状态。
  // ======================================================

  if (
    fireEmergency
  ) {

    finalLeft =
      RouteState::FIRE;

    finalRight =
      RouteState::FIRE;
  }
}


// ==========================================================
// 23. 蜂鸣器模式
// ==========================================================

BuzzerMode wantedBuzzerMode() {
  if (fireEmergency) return BuzzerMode::FIRE;
  if (manualAlarm) return BuzzerMode::MANUAL_ALARM;
  if (communicationOffline) return BuzzerMode::SILENT;

  // Any formal warning, crowd, danger, or fire buzzer takes priority.
  switch (maxState(finalLeft, finalRight)) {
    case RouteState::WARNING: return BuzzerMode::WARNING;
    case RouteState::CROWD: return BuzzerMode::CROWD;
    case RouteState::DANGER:
    case RouteState::FIRE: return BuzzerMode::FIRE;
    case RouteState::NORMAL: break;
  }
  return vision.runningEvent ? BuzzerMode::RUNNING : BuzzerMode::SILENT;
}


// ==========================================================
// 24. 蜂鸣器控制
// ==========================================================

void updateBuzzer() {
  BuzzerMode wanted = wantedBuzzerMode();
  if (wanted != currentBuzzerMode) {
    currentBuzzerMode = wanted;
    buzzerModeStartMs = millis();
    buzzerWrite(false);
  }

  uint32_t elapsed = millis() - buzzerModeStartMs;
  bool on = false;
  switch (currentBuzzerMode) {
    case BuzzerMode::SILENT: on = false; break;
    case BuzzerMode::WARNING: on = (elapsed % 2200UL) < 180UL; break;
    case BuzzerMode::CROWD: on = (elapsed % 300UL) < 150UL; break;
    case BuzzerMode::RUNNING: on = (elapsed % 2000UL) < 80UL; break;
    case BuzzerMode::MANUAL_ALARM: on = (elapsed % (MANUAL_ALARM_BUZZER_HALF_PERIOD_MS * 2UL)) < MANUAL_ALARM_BUZZER_HALF_PERIOD_MS; break;
    case BuzzerMode::FIRE: on = true; break;
  }
  buzzerWrite(on);
}

// ==========================================================
// 25. MAX7219 左右分流箭头
// ==========================================================

ArrowMode wantedArrowMode() {
  // During fire or manual alarm, do not show an unverified evacuation route.
  if (fireEmergency || manualAlarm) return ArrowMode::OFF;
  if (!piOnline()) return ArrowMode::OFF;
  if (vision.arrowModeProvided) return vision.arrowMode;
  // Compatibility with old Pi messages that only contained one direction.
  if (vision.recommendedDirectionProvided) {
    return vision.recommendedDirection == ArrowDirection::LEFT ? ArrowMode::LEFT_ONLY
      : vision.recommendedDirection == ArrowDirection::RIGHT ? ArrowMode::RIGHT_ONLY
      : ArrowMode::OFF;
  }
  return ArrowMode::OFF;
}

const char* arrowText(ArrowDirection direction) {
  switch (direction) {
    case ArrowDirection::LEFT: return "LEFT";
    case ArrowDirection::RIGHT: return "RIGHT";
    case ArrowDirection::NONE: return "NONE";
  }
  return "NONE";
}

ArrowDirection primaryArrowDirection(ArrowMode mode) {
  if (mode == ArrowMode::LEFT_ONLY) return ArrowDirection::LEFT;
  if (mode == ArrowMode::RIGHT_ONLY) return ArrowDirection::RIGHT;
  return ArrowDirection::NONE;
}

const char* arrowModeText(ArrowMode mode) {
  switch (mode) {
    case ArrowMode::OFF: return "OFF";
    case ArrowMode::LEFT_ONLY: return "LEFT_ONLY";
    case ArrowMode::RIGHT_ONLY: return "RIGHT_ONLY";
    case ArrowMode::LEFT_FLASH: return "LEFT_FLASH";
    case ArrowMode::RIGHT_FLASH: return "RIGHT_FLASH";
    case ArrowMode::BOTH_STEADY: return "BOTH_STEADY";
    case ArrowMode::BOTH_FLASH: return "BOTH_FLASH";
  }
  return "OFF";
}

void drawArrowMode(ArrowMode mode, bool visible) {
  if (!visible || mode == ArrowMode::OFF) {
    clearMatrices();
  } else if (mode == ArrowMode::LEFT_ONLY || mode == ArrowMode::LEFT_FLASH) {
    drawArrowOnDevice(MAX7219_LEFT_DEVICE, ARROW_LEFT);
  } else if (mode == ArrowMode::RIGHT_ONLY || mode == ArrowMode::RIGHT_FLASH) {
    drawArrowOnDevice(MAX7219_RIGHT_DEVICE, ARROW_RIGHT);
  } else {
    drawArrowPair(ARROW_LEFT, ARROW_RIGHT);
  }
}

void updateMatrices() {
  const ArrowMode wanted = wantedArrowMode();
  const bool flashing = wanted == ArrowMode::BOTH_FLASH || wanted == ArrowMode::LEFT_FLASH || wanted == ArrowMode::RIGHT_FLASH;
  const bool visible = !flashing || ((millis() / 350UL) % 2UL) == 0UL;
  if (wanted == currentArrowMode && visible == currentMatrixVisible) return;
  currentArrowMode = wanted;
  currentMatrixVisible = visible;
  drawArrowMode(wanted, visible);
  Serial.print("[MATRIX] mode=");
  Serial.println(arrowModeText(currentArrowMode));
}

// ==========================================================
// 25. 状态输出 + ESP32 -> Raspberry Pi
// ==========================================================

void printAndSendStatus() {

  uint32_t now =
    millis();


  if (
    now - lastReportMs <
    REPORT_INTERVAL_MS
  ) {

    return;
  }


  lastReportMs =
    now;


  // ======================================================
  // USB 串口监视器
  // ======================================================

  Serial.println();

  Serial.println(
    "========== HUAIAN STATUS =========="
  );


  Serial.print(
    "PI          : "
  );

  Serial.println(
    piOnline()
    ? "ONLINE"
    : "OFFLINE"
  );


  Serial.print(
    "LEFT STATE  : "
  );

  Serial.println(
    stateText(
      finalLeft
    )
  );


  Serial.print(
    "RIGHT STATE : "
  );

  Serial.println(
    stateText(
      finalRight
    )
  );


  Serial.print(
    "MQ2         : "
  );

  Serial.println(
    sensors.mq2Raw
  );


  Serial.print(
    "MQ2 SMOKE   : "
  );

  Serial.println(
    sensors.smokeWarning
    ? "YES"
    : "NO"
  );


  Serial.print(
    "TEMP        : "
  );

  if (
    sensors.dhtValid
  ) {

    Serial.print(
      sensors.temperatureC,
      1
    );

    Serial.println(
      " C"
    );

  } else {

    Serial.println(
      "ERROR"
    );
  }


  Serial.print(
    "HUM         : "
  );

  if (
    sensors.dhtValid
  ) {

    Serial.print(
      sensors.humidity,
      1
    );

    Serial.println(
      " %"
    );

  } else {

    Serial.println(
      "ERROR"
    );
  }


  Serial.print(
    "TEMP HIGH   : "
  );

  Serial.println(
    (
      sensors.dhtValid &&
      sensors.tempHigh
    )
    ? "YES"
    : "NO"
  );


  Serial.print(
    "PEOPLE      : "
  );

  Serial.println(
    vision.totalCount
  );


  Serial.print(
    "CROWD INDEX : "
  );

  Serial.println(
    vision.crowdIndex,
    2
  );


  Serial.print(
    "CONFLICT    : "
  );

  Serial.println(
    vision.conflict
    ? "YES"
    : "NO"
  );


  Serial.print(
    "VISION FIRE : "
  );

  Serial.println(
    vision.fireSuspected
    ? "YES"
    : "NO"
  );


  Serial.print(
    "VISION SMOKE: "
  );

  Serial.println(
    vision.smokeSuspected
    ? "YES"
    : "NO"
  );


  Serial.print(
    "LOCAL FIRE  : "
  );

  Serial.println(
    (
      piOnline() &&
      sensors.mq2Ready &&
      sensors.smokeWarning &&
      vision.fireConfirmed
    )
    ? "YES"
    : "NO"
  );


  Serial.print(
    "ENV FIRE    : "
  );

  Serial.println(
    fireEmergency
    ? "YES"
    : "NO"
  );


  Serial.print(
    "SYSTEM STATE: "
  );

  Serial.println(
    overallSystemState()
  );


  Serial.println(
    "=================================="
  );


  // ======================================================
  // ESP32 -> Raspberry Pi
  //
  // 严格保留 Pi 当前正式解析器需要的字段
  // ======================================================

  JsonDocument reply;


  reply["protocol_version"] =
    1;

  reply["message_type"] =
    "esp32_status";

  reply["uptime_ms"] =
    now;


  // MQ-2: publish the real baseline and phase for the Pi dashboard.
  reply["mq2_value"] =
    sensors.mq2Raw;
  reply["mq2_warning"] =
    sensors.smokeWarning;
  reply["mq2_phase"] =
    mq2PhaseText();
  reply["mq2_ready"] =
    sensors.mq2Ready;
  reply["mq2_warmup_remaining_ms"] =
    mq2WarmupRemainingMs();
  reply["mq2_calibration_remaining_ms"] =
    mq2CalibrationRemainingMs();
  if (sensors.mq2Ready) {
    reply["mq2_baseline"] = sensors.mq2Baseline;
    reply["mq2_trigger_threshold"] = sensors.mq2TriggerThreshold;
    reply["mq2_release_threshold"] = sensors.mq2ReleaseThreshold;
  } else {
    reply["mq2_baseline"] = nullptr;
    reply["mq2_trigger_threshold"] = nullptr;
    reply["mq2_release_threshold"] = nullptr;
  }


  // DHT11

  if (
    sensors.dhtValid
  ) {

    reply["temperature_c"] =
      sensors.temperatureC;

  } else {

    reply["temperature_c"] =
      nullptr;
  }


  reply["temperature_valid"] =
    sensors.dhtValid;


  reply["temperature_warning"] =
    (
      sensors.dhtValid &&
      sensors.tempHigh
    );


  // 综合状态

  reply["system_state"] =
    overallSystemState();


  // Pi -> ESP32 UART 当前是否有效

  reply["vision_valid"] =
    piOnline();
  reply["left_exit_state"] = stateText(finalLeft);
  reply["right_exit_state"] = stateText(finalRight);
  reply["left_exit_count"] = vision.leftCount;
  reply["right_exit_count"] = vision.rightCount;
  reply["arrow_direction"] = arrowModeText(currentArrowMode);
  reply["arrow_mode"] = arrowModeText(currentArrowMode);
  reply["manual_alarm"] = manualAlarm;
  reply["manual_alarm_remaining_ms"] = manualAlarmRemainingMs();
  reply["manual_alarm_source"] = "PS2_BUTTON";
  reply["recommended_direction"] = arrowText(primaryArrowDirection(currentArrowMode));


  // 可以额外回传湿度
  // 树莓派旧解析器即使暂时不用，
  // 也不会影响必需字段

  if (
    sensors.dhtValid
  ) {

    reply["humidity_percent"] =
      sensors.humidity;
  }


  serializeJson(
    reply,
    PiSerial
  );

  PiSerial.write(
    '\n'
  );

  // Mirror the formal status JSON to USB for the Windows teaching console.
  // PiSerial remains the production Raspberry Pi link.
  serializeJson(
    reply,
    Serial
  );

  Serial.write(
    '\n'
  );
}


// ==========================================================
// 26. SETUP
// ==========================================================

void setup() {

  // ---------- RGB ----------

  pinMode(
    LEFT_R,
    OUTPUT
  );

  pinMode(
    LEFT_G,
    OUTPUT
  );

  pinMode(
    LEFT_B,
    OUTPUT
  );


  pinMode(
    RIGHT_R,
    OUTPUT
  );

  pinMode(
    RIGHT_G,
    OUTPUT
  );

  pinMode(
    RIGHT_B,
    OUTPUT
  );


  // ---------- 蜂鸣器 ----------

  pinMode(
    BUZZER_PIN,
    OUTPUT
  );

  // ---------- PS2 摇杆 SW ----------

  pinMode(MANUAL_ALARM_SW_PIN, INPUT_PULLUP);
  lastButtonReading = digitalRead(MANUAL_ALARM_SW_PIN);
  stableButtonState = lastButtonReading;


  // ---------- MQ-2 ----------
  pinMode(
    MQ2_PIN,
    INPUT
  );


  // ======================================================
  // 上电默认：
  // 双绿灯
  // 蜂鸣器静音
  // ======================================================

  setLeft(
    false,
    true,
    false
  );

  setRight(
    false,
    true,
    false
  );

  buzzerWrite(
    false
  );


  // ---------- USB 串口 ----------

  Serial.begin(
    BAUD
  );


  // ---------- Raspberry Pi UART2 ----------

  PiSerial.begin(
    BAUD,
    SERIAL_8N1,
    PI_RX_PIN,
    PI_TX_PIN
  );

  // ---------- MAX7219 x2 ----------

  initMatrices();


  piBuffer.reserve(
    512
  );

  usbBuffer.reserve(
    512
  );


  // ---------- ESP32 ADC ----------

  analogReadResolution(
    12
  );

  analogSetPinAttenuation(
    MQ2_PIN,
    ADC_11db
  );


  // ---------- DHT11 ----------

  dht.begin();


  delay(
    500
  );


  Serial.println();

  Serial.println(
    "========================================"
  );

  Serial.println(
    " Huian ESP32 Final Integrated Program "
  );

  Serial.println(
    " RGB mapping : L R27 G32 B26 / R R33 G13 B14"
  );

  Serial.println(
    " NORMAL GREEN / WARNING BLUE / CROWD-DANGER YELLOW / MANUAL PURPLE / FIRE RED"
  );

  Serial.println(
    " Pi offline  : PURPLE BLINK / SILENT"
  );

  Serial.println(
    " Fire        : RED BLINK / BUZZER"
  );

  Serial.println(
    " UART        : 115200 8N1"
  );

  Serial.println(
    " ESP32 status protocol : esp32_status"
  );

  Serial.println(
    "========================================"
  );
}


// ==========================================================
// 27. LOOP
// ==========================================================

void loop() {

  // ======================================================
  // Raspberry Pi -> ESP32
  // ======================================================

  readJsonStream(
    PiSerial,
    piBuffer,
    "RPI_UART"
  );


  // ======================================================
  // Arduino 串口监视器
  // 也可以发送一行 JSON 模拟树莓派
  // ======================================================

  readJsonStream(
    Serial,
    usbBuffer,
    "USB_TEST"
  );
  // ---------- PS2 摇杆人工报警 ----------

  updateManualAlarmButton();


  // ======================================================
  // 传感器
  // ======================================================

  updateSensors();


  // ======================================================
  // 风险判断
  // ======================================================

  evaluateRisk();


  // ======================================================
  // RGB
  //
  // 优先级：
  // FIRE > 人工报警 > 普通风险
  // ======================================================

  if (
    fireEmergency
  ) {

    showLeftState(
      RouteState::FIRE
    );

    showRightState(
      RouteState::FIRE
    );

  } else if (
    manualAlarm
  ) {

    showManualAlarm();
  } else {

    showLeftState(
      finalLeft
    );

    showRightState(
      finalRight
    );
  }


  // ======================================================
  // 蜂鸣器
  // ======================================================

  updateBuzzer();
  // ---------- MAX7219 双出口分流 ----------

  updateMatrices();


  // ======================================================
  // 串口状态 + 回传树莓派
  // ======================================================

  printAndSendStatus();


  delay(
    2
  );
}