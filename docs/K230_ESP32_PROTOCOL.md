# K230 to ESP32 protocol and fire fusion

Transport is UART, UTF-8 JSON, one object per line. Protocol version is `1`.

```json
{"protocol_version":1,"device":"Huian_Loudao_01","vision_risk":"CROWD","crowd_index":0.78,"left_people":6,"right_people":5,"total_people":11,"direction_conflict":true,"timestamp":123456}
```

K230 owns only visual state. ESP32 owns sensor reading, final fusion and alarm control.

| Final state | Condition | RGB | Buzzer |
| --- | --- | --- | --- |
| `SYSTEM_NORMAL` | no visual danger or confirmed fire | green | off |
| `CROWD_WARNING` | `vision_risk=CROWD` | yellow | periodic |
| `CROWD_DANGER` | `vision_risk=DANGER` | blinking red | fast |
| `FIRE_EMERGENCY` | smoke + temperature warning, or smoke + visual DANGER | solid red | continuous fast pattern |

MQ-2 alone never declares `FIRE_EMERGENCY`. The temperature implementation is deliberately an interface only until DS18B20, DHT or NTC hardware is selected.

All pin numbers and serial settings in `esp32_firmware/config.h` are placeholders. Confirm the ESP32 model, UART port, pins, sensor type and wiring before compiling or uploading.
