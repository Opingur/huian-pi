# 正式源码架构

## 数据流

```text
Pi IMX219                         Windows 原始 MP4
PicameraSource                    VideoSource
         │ BGR frame + source_time │
         └────────────┬────────────┘
                      ▼
     TrackedFrameProcessor（正式组合根）
                      ▼
YOLO person → ByteTrack → Trajectory / Direction / Running
                      ▼
PeopleFlow / Flow groups → Crowd Index / Prediction → Risk
                      ▼
Dashboard overlay + status.jsonl + ESP32Publisher
```

`source_time` 由输入源提供：视频使用视频时间轴，Pi 使用启动后的单调时间；两者都不以推理耗时作为视频证据。

## 模块职责

| 层 | 位置 | 职责 |
| --- | --- | --- |
| 输入 | `rpi_app/sources/` | `VideoSource` 与延迟导入 Picamera2 的 `PicameraSource`，统一提供 BGR 帧和 source time |
| 视觉 | `rpi_app/vision/` | person detection、ByteTrack、轨迹、方向、流组、视觉火焰、跑动检测；`video_runner.py` 的处理器只组合既有模块 |
| 决策 | `rpi_app/decision/` | Crowd Index、短时预测、空间汇合和视觉风险 |
| 通信 | `rpi_app/communication/` | Pi↔ESP32 协议字段、JSON 编码、惰性 UART 打开和状态解析 |
| 正式 UI | `rpi_app/ui/` | Dashboard 与视觉 overlay；不计算算法或拼 UART JSON |
| 运行入口 | `rpi_app/main.py`、`rpi_app/runners/` | Pi 主运行和 Windows 原始视频演示 |
| 教学台 | `teaching_console/` | 直接调用正式模块，不复制 Crowd/Tracking 算法 |
| 验证 | `validation/` | 人工 Ground Truth、MAE 与验证工具 |

## 平台边界

- Pi 模式只有 `PicameraSource.start()` 才导入 `picamera2`。
- Windows `video_demo` 默认禁用 ESP32；仅指定 `--serial-port COMx` 才打开 USB Serial。
- `ESP32Publisher` 只有在 `enabled=true` 且 `dry_run=false` 时才导入并打开 pyserial。
- `CROWD` 是正式拥挤报警；`DANGER` 与 `FIRE` 由 ESP32 的火情语义处理，视觉人流不把普通拥挤升级为 DANGER。

## 配置和输出

`rpi_app/configs/` 保留正式主配置、硬件配置与固定案例配置，详见其中 README。配置相对路径按 `rpi_app/` 解析；正式输出统一配置为 `../output/...`，即项目根 `output/`。

历史 K230、早期 PC 原型、旧配置、旧发布快照及历史运行结果不属于正式开发仓库，已移至项目同级 `Huian_YOLO_Archive/`。正式源码、测试和 Teaching Console 不依赖该目录。
