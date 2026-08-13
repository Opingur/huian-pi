#pragma once

#define UART_BAUD 115200
#define UART_PROTOCOL_VERSION 1
#define VISION_UART_TIMEOUT_MS 5000UL

// Verified ESP32 wiring.
#define BUZZER_PIN 25
#define MQ2_PIN 34
#define DHT11_PIN 4

#define LEFT_RGB_R_PIN 27
#define LEFT_RGB_G_PIN 32
#define LEFT_RGB_B_PIN 26
#define RIGHT_RGB_R_PIN 33
#define RIGHT_RGB_G_PIN 13
#define RIGHT_RGB_B_PIN 14

#define VISION_UART_RX_PIN 16
#define VISION_UART_TX_PIN 17
#define VISION_UART_PORT Serial2

// Bench-calibrated prototype threshold; not a certified fire-safety threshold.
#define MQ2_TRIGGER_THRESHOLD 200
#define MQ2_RELEASE_THRESHOLD 120
#define MQ2_CONFIRM_SAMPLES 3
#define MQ2_RELEASE_SAMPLES 3
#define MQ2_SAMPLE_INTERVAL_MS 500UL

// Prototype/demo engineering threshold; not a certified fire-safety threshold.
#define TEMPERATURE_THRESHOLD 35.0f

#define BUZZER_SLOW_INTERVAL_MS 900UL
#define BUZZER_FAST_INTERVAL_MS 180UL
#define CROWD_DANGER_BLINK_INTERVAL_MS 400UL
#define FIRE_BLINK_INTERVAL_MS 200UL
#define COMM_TIMEOUT_BLINK_INTERVAL_MS 800UL
#define USB_DEBUG_INTERVAL_MS 1000UL
#define ESP32_STATUS_SEND_INTERVAL_MS 1000UL

// Temporary Raspberry Pi person-detection UART integration test. Keep 0 for formal alarms.
#define PERSON_LINK_TEST_MODE 0
#define PERSON_LINK_BEEP_DURATION_MS 150UL