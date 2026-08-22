# 慧安楼道（Huian_YOLO）

面向楼道安全教学与实验验证的视觉系统：树莓派 IMX219 实时输入或 Windows 原始 MP4 输入，共享 YOLO person 检测、ByteTrack、轨迹/方向、流组、Crowd Index、短时预测、风险状态、正式 Dashboard 与 ESP32 UART 协议；`teaching_console/` 提供独立教学与 Ground Truth 工具。

## 正式架构

```text
PicameraSource / VideoSource
        ↓ BGR frame + source_time
TrackedFrameProcessor
        ↓
YOLO → ByteTrack → Trajectory / Direction / Running
        ↓
Crowd Index / Prediction / Risk
        ↓
Dashboard + status.jsonl + ESP32 JSON
```

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 正式入口

在项目根目录执行：

```powershell
# Raspberry Pi 5 + IMX219（仅 Pi 需安装 Picamera2）
python -m rpi_app.main --config rpi_app/configs/rpi_imx219_live.json

# Windows：对原始 MP4 执行正式 YOLO / ByteTrack / Dashboard 链，不连接 ESP32
python -m rpi_app.runners.video_demo --video test_data/000327.mp4 --no-esp32

# Windows 教学与调试台
python -m teaching_console.main
```

Windows 视频输入必须是未绘制 Dashboard 的原始视频。比赛展示成品已外移到项目同级 `Huian_YOLO_Archive/final_dashboard_videos/`，不能作为重新推理输入。

## 主要目录

| 目录 | 职责 |
| --- | --- |
| `rpi_app/` | 正式视觉、决策、Dashboard、UART 与核心测试 |
| `teaching_console/` | Windows 教学、调试、Ground Truth、模型优化工具 |
| `esp32_firmware/` | 正式 ESP32 固件 |
| `validation/` | 标注、Ground Truth、验证脚本与模板 |
| `models/` | YOLO person / fire 模型 |
| `test_data/` | 原始固定案例及测试图像 |
| `scripts/` | 维护工具，例如 ONNX 导出 |
| `output/` | 轻量、可再生成的运行结果；已受 Git 忽略 |

四个原始教学案例：`000318`、`000327`、`000345`、`000353`，均在 `test_data/` 中保留可用路径。

## 输出、模型与用户数据

- 所有正式视觉运行输出写入项目根 `output/`。
- 正式模型放在 `models/`；当前 person 基线是 `models/yolov8n.pt`。
- Teaching Console 源码模式将用户数据保存在项目目录；EXE 模式保存到 EXE 同级的 `huian_teaching_data/`，绝不写入 PyInstaller 临时目录。
- `annotation_frames/` 是现有模型优化 SQLite 记录引用的用户标注帧，暂保留在根目录以避免损坏已有研究记录。
- 历史 K230、旧 PC 原型、旧配置、历史输出和比赛成品已移至项目同级 `Huian_YOLO_Archive/`；正式代码不依赖该目录。
- Windows 发布包已移至项目同级 `Huian_YOLO_Releases/`，可由源码与 `慧安楼道教学调试台.spec` 重新构建。

## 回归检查

```powershell
python -m compileall -q rpi_app teaching_console training
python -m pytest -q
python -m unittest discover -s teaching_console/tests -v
```

完整环境、部署说明和平台依赖见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。