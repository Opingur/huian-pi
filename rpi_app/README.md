# 慧安楼道正式视觉端

`rpi_app/` 是正式视觉核心：YOLOv8 person 检测、ByteTrack、轨迹/方向、流组、Crowd Index、短时预测、跑动辅助事件、Dashboard 和 Pi↔ESP32 UART。

## 入口

```powershell
# Pi IMX219 正式实时运行（仅 Raspberry Pi）
python -m rpi_app.main --config rpi_app/configs/rpi_imx219_live.json

# Windows 原始 MP4 正式演示（默认不连接 ESP32）
python -m rpi_app.runners.video_demo --video test_data/000327.mp4 --no-esp32
```

`python -m rpi_app.main --help` 可查看通用参数。配置内相对路径从 `rpi_app/` 解析；所有 `output_dir` 已收敛为 `../output/...`，即项目根 `output/`。

## 输入源与共享算法

- `sources/picamera_source.py`：只在 Pi 的 `start()` 阶段导入 Picamera2，返回 BGR 帧和单调 `source_time`。
- `sources/video_source.py`：读取原始 MP4/AVI/MOV，返回 BGR 帧和视频时间轴 `source_time`。
- `vision/video_runner.py:TrackedFrameProcessor`：两类输入共用的正式处理组合根。

实时 Pi 链保留最新帧 worker 策略，离线视频按帧处理；二者共享同一检测、跟踪、轨迹、预测、风险和跑动实现。

## 风险与通信

`NORMAL → WARNING → CROWD` 为视觉人流状态；高 Crowd Index、人数兜底和空间汇合只会产生 `CROWD`，不会把普通拥挤写成火警 `DANGER`。跑动只附加 `running_event/running_count`，不提升视觉风险。

ESP32 UART 是双向紧凑 JSON 协议。Windows video demo 默认 dry-run，只有 `--serial-port COMx` 才使用真实 USB Serial。详见 `docs/UART_PROTOCOL.md`。

## 配置

`configs/rpi_imx219_live.json` 是 Pi 硬件配置；`configs/demo_*.json` 与 `configs/final_dashboard_*.json` 是固定测试/复现实验配置。`configs/README.md` 说明每类用途。四个教学原始视频始终保留在 `test_data/`，不使用渲染成品视频。

完整仓库架构和部署见根 `README.md`、`docs/ARCHITECTURE.md` 与 `docs/DEPLOYMENT.md`。