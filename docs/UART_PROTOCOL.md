# Raspberry Pi 5 to ESP32 UART protocol

Huian Loudao uses a one-way Raspberry Pi 5 -> ESP32 protocol: **115200 baud, 8N1, 3.3 V TTL**, newline-delimited compact UTF-8 JSON, and `protocol_version: 1`.

## Raspberry Pi 5 UART0

The project UART0 is enabled with this Raspberry Pi 5-only boot configuration:

```text
dtoverlay=uart0-pi5
```

This places UART0 on the 40-pin header:

- GPIO14 / physical Pin 8: `TXD0`
- GPIO15 / physical Pin 10: `RXD0`
- GND: common ground
- Linux device: `/dev/ttyAMA0`

On the verified Raspberry Pi 5, `/dev/serial0 -> ttyAMA10` is the Pi 5 Debug UART. Huian Loudao must **not** use `/dev/serial0` for ESP32 communication.

## Formal wiring

- Raspberry Pi 5 GPIO14 / TXD0 -> ESP32 GPIO16 / RX2
- Raspberry Pi 5 GPIO15 / RXD0 <- ESP32 GPIO17 / TX2
- Raspberry Pi 5 GND <-> ESP32 GND

Both ends are 3.3 V TTL UART. Do not connect 5 V to UART TX/RX.

## Protocol payload

Each message contains only these fields:

```json
{"protocol_version":1,"timestamp":1720000000,"vision_risk":"CROWD","crowd_index":0.72,"total_people":12,"direction_conflict":true,"vision_fire_suspected":false,"vision_smoke_suspected":true,"vision_fire_confidence":0.0,"vision_smoke_confidence":0.81}
```

`vision_risk` describes person-flow/crowd risk only. It is never visual fire evidence. `vision_fire_suspected` and `vision_smoke_suspected` originate only from the Fire/Smoke YOLO temporal evidence. Bounding boxes, trajectories, flow groups, convergence points, prediction values, and dashboard details are deliberately excluded.

The ESP32 clears stale vision state after five seconds without a complete valid message. That produces `COMM_TIMEOUT` (blue RGB and silent buzzer). Local MQ-2 plus DHT evidence can still produce `FIRE_EMERGENCY` during a UART timeout.

## Application configuration

Use the `esp32` block in `rpi_app/configs/rpi_imx219_live.json` for Pi 5 camera deployment. Its default port is `/dev/ttyAMA0`; keep `enabled: false` and `dry_run: true` for normal desktop work. For hardware use, set `enabled: true`, `dry_run: false`, and keep the port as `/dev/ttyAMA0`. The publisher opens once, sends at `send_interval_seconds`, and closes when the runner exits. It imports `pyserial` only for enabled, non-dry UART use.