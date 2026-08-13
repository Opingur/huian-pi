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

  依赖：
  - DHT sensor library
  - Adafruit Unified Sensor
  - ArduinoJson 7

  当前测试阈值：
  MQ-2 触发：300
  MQ-2 解除：120
  温度：35.0 ℃

  最终状态语义：
  绿色常亮：正常
  黄色闪烁：拥挤/烟雾预警
  红色闪烁 + 蜂鸣器持续报警：火警
  紫色闪烁 + 静音：树莓派通信离线

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

// 左 RGB —— 成品实测后的真实映射
constexpr uint8_t LEFT_R = 32;
constexpr uint8_t LEFT_G = 26;
constexpr uint8_t LEFT_B = 27;

// 右 RGB —— 成品实测后的真实映射
constexpr uint8_t RIGHT_R = 13;
constexpr uint8_t RIGHT_G = 14;
constexpr uint8_t RIGHT_B = 33;

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


// ==========================================================
// 2. 通信与采样参数
// ==========================================================

constexpr uint32_t BAUD = 115200;

constexpr uint32_t VISION_TIMEOUT_MS = 5000UL;

constexpr uint32_t MQ2_INTERVAL_MS = 500UL;
constexpr uint32_t DHT_INTERVAL_MS = 2500UL;
constexpr uint32_t REPORT_INTERVAL_MS = 1000UL;


// ==========================================================
// 3. 当前演示测试阈值
// ==========================================================

constexpr uint16_t MQ2_TRIGGER_THRESHOLD = 300;
constexpr uint16_t MQ2_RELEASE_THRESHOLD = 120;

constexpr uint8_t MQ2_CONFIRM_SAMPLES = 3;
constexpr uint8_t MQ2_RELEASE_SAMPLES = 3;

constexpr float TEMP_FIRE_TEST_THRESHOLD = 35.0F;


// ==========================================================
// 4. 状态定义
// ==========================================================

enum class RouteState : uint8_t {
  NORMAL,
  WARNING,
  DANGER,
  FIRE
};


enum class BuzzerMode : uint8_t {
  SILENT,
  WARNING,
  ONE_DANGER,
  MIXED_HIGH,
  BOTH_DANGER,
  FIRE
};


// ==========================================================
// 5. 树莓派视觉数据
// ==========================================================

struct VisionData {

  RouteState left = RouteState::NORMAL;
  RouteState right = RouteState::NORMAL;

  int leftCount = 0;
  int rightCount = 0;
  int totalCount = 0;

  float crowdIndex = 0.0F;

  bool conflict = false;

  bool fireSuspected = false;
  bool smokeSuspected = false;

  float fireConfidence = 0.0F;
  float smokeConfidence = 0.0F;

  bool fireConfirmed = false;

  uint32_t lastRxMs = 0;

  bool valid = false;
};


// ==========================================================
// 6. ESP32 本地传感器数据
// ==========================================================

struct SensorData {

  uint16_t mq2Raw = 0;

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

  if (!raw) {
    return RouteState::NORMAL;
  }

  String s(raw);

  s.trim();
  s.toUpperCase();


  if (
    s == "NORMAL" ||
    s == "CLEAR"
  ) {

    return RouteState::NORMAL;
  }


  if (
    s == "WARNING" ||
    s == "ATTENTION" ||
    s == "CROWD_WARNING"
  ) {

    return RouteState::WARNING;
  }


  if (
    s == "CROWD" ||
    s == "CROWDED" ||
    s == "DANGER" ||
    s == "CROWD_DANGER"
  ) {

    return RouteState::DANGER;
  }


  if (
    s == "FIRE" ||
    s == "FIRE_EMERGENCY"
  ) {

    return RouteState::FIRE;
  }


  return RouteState::NORMAL;
}


// ==========================================================
// 11. 风险等级
// ==========================================================

int stateRank(RouteState state) {

  switch (state) {

    case RouteState::NORMAL:
      return 0;

    case RouteState::WARNING:
      return 1;

    case RouteState::DANGER:
      return 2;

    case RouteState::FIRE:
      return 3;
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

  // 火警优先级最高，即使树莓派离线也必须报火警
  if (fireEmergency) {
    return "FIRE";
  }

  // 树莓派通信超时：紫色闪烁、蜂鸣器静音
  if (communicationOffline) {
    return "COMM_TIMEOUT";
  }

  RouteState overall =
    maxState(
      finalLeft,
      finalRight
    );


  switch (overall) {

    case RouteState::NORMAL:
      return "NORMAL";

    case RouteState::WARNING:
      return "WARNING";

    case RouteState::DANGER:
      return "DANGER";

    case RouteState::FIRE:
      return "FIRE";
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

    // 正常：绿色常亮
    case RouteState::NORMAL:

      return true;


    // 黄色慢闪
    case RouteState::WARNING:

      return
        ((now / 600UL) % 2UL)
        == 0UL;


    // 红色快闪
    case RouteState::DANGER:

      return
        ((now / 250UL) % 2UL)
        == 0UL;


    // 紫色快速闪
    case RouteState::FIRE:

      return
        ((now / 200UL) % 2UL)
        == 0UL;
  }


  return true;
}


// ==========================================================
// 14. 左 RGB
// ==========================================================

void showLeftState(RouteState state) {

  uint32_t now = millis();

  bool visible =
    stateBlinkOn(
      state,
      now
    );


  if (!visible) {

    setLeft(
      false,
      false,
      false
    );

    return;
  }


  switch (state) {

    // 绿色
    case RouteState::NORMAL:

      setLeft(
        false,
        true,
        false
      );

      break;


    // 黄色 = 红 + 绿
    case RouteState::WARNING:

      setLeft(
        true,
        true,
        false
      );

      break;


    // 红色
    case RouteState::DANGER:

      setLeft(
        true,
        false,
        false
      );

      break;


    // 火警：红色
    case RouteState::FIRE:

      setLeft(
        true,
        false,
        false
      );

      break;
  }
}


// ==========================================================
// 15. 右 RGB
// ==========================================================

void showRightState(RouteState state) {

  uint32_t now = millis();

  bool visible =
    stateBlinkOn(
      state,
      now
    );


  if (!visible) {

    setRight(
      false,
      false,
      false
    );

    return;
  }


  switch (state) {

    case RouteState::NORMAL:

      setRight(
        false,
        true,
        false
      );

      break;


    case RouteState::WARNING:

      setRight(
        true,
        true,
        false
      );

      break;


    case RouteState::DANGER:

      setRight(
        true,
        false,
        false
      );

      break;


    case RouteState::FIRE:

      setRight(
        true,
        false,
        false
      );

      break;
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


  // 如果没有左右独立风险，
  // 两侧都使用 vision_risk

  const char* leftRisk =
    doc["left_risk"] | globalRisk;

  const char* rightRisk =
    doc["right_risk"] | globalRisk;


  vision.left =
    parseState(leftRisk);

  vision.right =
    parseState(rightRisk);


  // ---------- 人数 ----------

  if (
    !doc["left_count"].isNull()
  ) {

    vision.leftCount =
      doc["left_count"].as<int>();
  }


  if (
    !doc["right_count"].isNull()
  ) {

    vision.rightCount =
      doc["right_count"].as<int>();
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

void updateMq2State() {

  sensors.mq2Raw =
    readMq2RawAverage();


  // ======================================================
  // 当前无烟雾状态
  // ======================================================

  if (
    !sensors.smokeWarning
  ) {

    sensors.mq2LowCount = 0;


    if (
      sensors.mq2Raw >=
      MQ2_TRIGGER_THRESHOLD
    ) {

      if (
        sensors.mq2HighCount <
        MQ2_CONFIRM_SAMPLES
      ) {

        sensors.mq2HighCount++;
      }


      if (
        sensors.mq2HighCount >=
        MQ2_CONFIRM_SAMPLES
      ) {

        sensors.smokeWarning =
          true;

        sensors.mq2HighCount =
          0;
      }

    } else {

      sensors.mq2HighCount =
        0;
    }
  }


  // ======================================================
  // 当前已经进入烟雾状态
  // ======================================================

  else {

    sensors.mq2HighCount = 0;


    if (
      sensors.mq2Raw <=
      MQ2_RELEASE_THRESHOLD
    ) {

      if (
        sensors.mq2LowCount <
        MQ2_RELEASE_SAMPLES
      ) {

        sensors.mq2LowCount++;
      }


      if (
        sensors.mq2LowCount >=
        MQ2_RELEASE_SAMPLES
      ) {

        sensors.smokeWarning =
          false;

        sensors.mq2LowCount =
          0;
      }

    } else {

      sensors.mq2LowCount =
        0;
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
        TEMP_FIRE_TEST_THRESHOLD;
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
      vision.left;

    finalRight =
      vision.right;

  } else {

    finalLeft =
      RouteState::NORMAL;

    finalRight =
      RouteState::NORMAL;
  }


  fireEmergency =
    false;


  // ======================================================
  // 2. 树莓派明确确认火情
  // ======================================================

  if (
    online &&
    vision.fireConfirmed
  ) {

    fireEmergency =
      true;
  }


  // ======================================================
  // 3. ESP32 本地环境火情
  //
  // MQ-2 烟雾
  // +
  // DHT11 温度 >= 35℃
  //
  // 注意：
  // 这条本地安全链不依赖树莓派在线。
  // 即使 Pi 离线，只要满足条件，
  // 仍然必须进入 FIRE。
  // ======================================================

  bool localEnvironmentFire =

    sensors.smokeWarning &&

    sensors.dhtValid &&

    sensors.tempHigh;


  if (
    localEnvironmentFire
  ) {

    fireEmergency =
      true;
  }


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

  if (
    fireEmergency
  ) {

    return
      BuzzerMode::FIRE;
  }

  // 树莓派离线：紫色闪烁，但蜂鸣器保持静音
  if (
    communicationOffline
  ) {

    return
      BuzzerMode::SILENT;
  }


  bool leftDanger =
    finalLeft ==
    RouteState::DANGER;

  bool rightDanger =
    finalRight ==
    RouteState::DANGER;

  bool leftWarning =
    finalLeft ==
    RouteState::WARNING;

  bool rightWarning =
    finalRight ==
    RouteState::WARNING;


  if (
    leftDanger &&
    rightDanger
  ) {

    return
      BuzzerMode::BOTH_DANGER;
  }


  if (
    (
      leftDanger &&
      rightWarning
    ) ||
    (
      rightDanger &&
      leftWarning
    )
  ) {

    return
      BuzzerMode::MIXED_HIGH;
  }


  if (
    leftDanger ||
    rightDanger
  ) {

    return
      BuzzerMode::ONE_DANGER;
  }


  if (
    leftWarning ||
    rightWarning
  ) {

    return
      BuzzerMode::WARNING;
  }


  return
    BuzzerMode::SILENT;
}


// ==========================================================
// 24. 蜂鸣器控制
// ==========================================================

void updateBuzzer() {

  BuzzerMode wanted =
    wantedBuzzerMode();


  if (
    wanted !=
    currentBuzzerMode
  ) {

    currentBuzzerMode =
      wanted;

    buzzerModeStartMs =
      millis();

    buzzerWrite(false);
  }


  uint32_t elapsed =
    millis() -
    buzzerModeStartMs;


  bool on =
    false;


  switch (
    currentBuzzerMode
  ) {

    // 正常
    case BuzzerMode::SILENT:

      on = false;

      break;


    // 黄色警告
    // 每约2.2秒短响一次
    case BuzzerMode::WARNING: {

      uint32_t phase =
        elapsed %
        2200UL;

      on =
        phase <
        180UL;

      break;
    }


    // 单侧危险
    // 3次快速短鸣
    case BuzzerMode::ONE_DANGER: {

      uint32_t phase =
        elapsed %
        1800UL;

      on =
        phase < 720UL &&
        (
          (
            phase /
            120UL
          ) %
          2UL
          ==
          0UL
        );

      break;
    }


    // 一侧危险 + 一侧警告
    case BuzzerMode::MIXED_HIGH: {

      uint32_t phase =
        elapsed %
        2300UL;

      on =
        phase < 1440UL &&
        (
          (
            phase /
            90UL
          ) %
          2UL
          ==
          0UL
        );

      break;
    }


    // 双侧危险
    case BuzzerMode::BOTH_DANGER: {

      uint32_t phase =
        elapsed %
        300UL;

      on =
        phase <
        150UL;

      break;
    }


    // 火情
    // 持续报警
    case BuzzerMode::FIRE:

      on = true;

      break;
  }


  buzzerWrite(on);
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
      sensors.smokeWarning &&
      sensors.dhtValid &&
      sensors.tempHigh
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


  // MQ-2

  reply["mq2_value"] =
    sensors.mq2Raw;

  reply["mq2_warning"] =
    sensors.smokeWarning;


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
    " RGB mapping : FINAL PRODUCT"
  );

  Serial.println(
    " Normal      : GREEN"
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
  // FIRE > COMM_TIMEOUT > 普通风险
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
    communicationOffline
  ) {

    showCommunicationOffline();

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


  // ======================================================
  // 串口状态 + 回传树莓派
  // ======================================================

  printAndSendStatus();


  delay(
    2
  );
}