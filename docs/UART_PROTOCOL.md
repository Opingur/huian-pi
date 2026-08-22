# Pi ↔ ESP32 UART 协议

传输为 115200、8N1、3.3 V TTL、UTF-8 紧凑 JSON，一行一个对象，`protocol_version` 为 `1`。Pi 硬件端使用 `/dev/ttyAMA0`；Windows video demo 只有显式指定 `--serial-port COMx` 才会打开 USB 串口。

## Pi → ESP32 视觉载荷

```json
{"protocol_version":1,"timestamp":1720000000,"vision_risk":"CROWD","crowd_index":0.72,"total_people":12,"direction_conflict":true,"vision_fire_suspected":false,"vision_smoke_suspected":false,"vision_fire_confidence":0.0,"vision_smoke_confidence":0.0,"running_event":true,"running_count":1}
```

`running_event` / `running_count` 仅是低优先级跑动轻提示，不改写 `vision_risk`。Pi 发送字段由 `rpi_app/communication/esp32.py:UART_FIELDS` 唯一维护；任何 Dashboard、轨迹或框数据都不进入协议。

## ESP32 → Pi 状态镜像

ESP32 同时向 Pi UART2 和 USB Serial 输出：

```json
{"protocol_version":1,"message_type":"esp32_status","uptime_ms":1234,"mq2_value":0,"mq2_warning":false,"temperature_c":28.0,"temperature_valid":true,"temperature_warning":false,"system_state":"CROWD","vision_valid":true}
```

Pi 接受 `NORMAL`、`WARNING`、`CROWD`、历史兼容 `CROWD_WARNING/CROWD_DANGER`、`DANGER`、`FIRE` 与 `COMM_TIMEOUT`。正式固件的状态语义、GPIO 与本地 MQ-2/DHT11 融合保持在 `esp32_firmware/huian_esp32/huian_esp32.ino`。