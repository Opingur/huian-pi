# 慧安楼道｜教学与调试台 v0.1

这是 Huian_YOLO 仓库中的独立 Windows 教学工具。第一阶段提供：系统总览、真实源码地图，以及通过 USB Serial 向 ESP32 注入与 Raspberry Pi 正式协议兼容的视觉 JSON。

它不会运行 YOLO、视频、ByteTrack 或修改 Crowd Index 参数；这些交互实验留给下一阶段。

## 课堂状态语义

| JSON `vision_risk` | 课堂含义 | 预期硬件响应 |
| --- | --- | --- |
| `NORMAL` | 正常 | 绿灯常亮；蜂鸣器静音 |
| `WARNING` | 一般预警 | 蓝灯常亮；慢速短促蜂鸣 |
| `CROWD` | 拥挤报警 | 黄色闪烁；快速、连续、短促蜂鸣 |
| `DANGER` | 火警 | 红灯快速闪烁；蜂鸣器持续长鸣 |

## 安装与启动

在仓库根目录执行：

```powershell
python -m pip install pyserial
python -m teaching_console.main
```

Tkinter 随普通 Windows Python 安装提供。未安装 `pyserial` 时，总览和源码地图仍能打开；连接串口时会显示安装提示。

## 连接 ESP32

1. 给 ESP32 烧录 `esp32_firmware/huian_esp32/huian_esp32.ino`。
2. 用 USB 数据线连接 Windows 电脑。
3. 在“ESP32实验”页点击“刷新串口”，选择出现的 `COMx`。
4. 保持 115200，点击“连接”。
5. 顶部会显示“ESP32：已连接”，下方原始日志会显示 RX/TX。

ESP32 拔掉或串口异常时，后台读取线程会记录错误并把界面恢复为未连接；窗口关闭时会主动关闭串口。

如果 COM 口被 Arduino IDE、串口助手或其他程序占用，请关闭占用程序后点击“刷新串口”和“连接”。

## 一次课堂实验

1. 打开“系统总览”，说明视频/摄像头由 `PersonTracker.track()` 内部完成 YOLO person 检测与 ByteTrack，而 `PersonDetector` 仅用于图片单帧旧链。
2. 在“源码地图”中选中 `rpi_app/communication/esp32.py`，说明正式 Pi 载荷有 10 个字段。
3. 在“ESP32实验”中先点击 `NORMAL 示例`。案例只会载入编辑器，不会自动发出。
4. 让学生检查 JSON，点击“发送到ESP32”。ESP32 的 USB 输入会走与 Pi UART2 相同的 `readJsonStream → parseVisionJson`。
5. 分别加载并发送 `WARNING`、`CROWD`、`DANGER` 示例；编辑器下方会显示该案例的预期硬件响应。
6. 观察下方原始日志和“ESP32 回传解析状态”：`esp32_status` 会显示 MQ-2 ADC、温度、系统状态和 vision_valid。

`协议错误示例` 与 `非法 JSON 示例` 同样只加载，适合先讨论再决定是否发送。非法 JSON 无法通过教学台发送。

## 协议与安全边界

- 发送使用正式 Pi v1 JSON：UTF-8、紧凑单行、换行结尾。
- 当前正式 Pi payload 的 visual smoke 字段固定为 `false / 0.0`，界面会保留并说明该事实。
- ESP32 USB 上仍会存在普通调试文本。教学台只把完整的 `message_type: "esp32_status"` JSON 作为状态，其他行只进入原始日志。
- 本版本只做真实代码说明：正式 `convergence_score` 不直接读取 Conflict Zone；未完成 crowd calibration 时，`time_to_danger` 不会伪造为倒计时。
- `esp32_firmware/huian_esp32/src/` 在源码地图中标为 inactive，因为正式 `.ino` 未接入它。

## 真实源码入口

- 视频 / 相机追踪：`rpi_app/vision/tracker.py`
- 轨迹和方向：`rpi_app/vision/trajectory.py`
- 空间汇合：`rpi_app/decision/flow_analysis.py`
- Crowd Index：`rpi_app/decision/crowd_index.py`
- Pi ↔ ESP32 UART：`rpi_app/communication/esp32.py`
- 正式 ESP32 草图：`esp32_firmware/huian_esp32/huian_esp32.ino`

## 本阶段未做

视频播放器、ByteTrack 动画、轨迹 Canvas、趋势 / Crowd Index 权重交互、Ground Truth 编辑器、EXE 打包和主题美化均未包含。

## 第二阶段：YOLO / Tracking 实验

启动后打开“YOLO / Tracking”页。默认示例是仓库输入视频 `test_data/000327.mp4`；该页不会使用 `final_dashboard_videos/` 中的渲染结果。也可以选择本地 `.mp4/.avi/.mov/.mkv` 视频。

固定教学案例全部是可重新推理的原始输入，选择后会在页内显示案例编号和用途：

- `000318`：人数增长（`test_data/iitb_final/000318.mp4`）
- `000327`：目标跟踪 / Track ID（`test_data/000327.mp4`，默认）
- `000345`：人数下降（`test_data/iitb_final/000345.mp4`）
- `000353`：增长 / 趋势（`test_data/iitb_final/000353.mp4`）

这些路径也分别被 `rpi_app/configs/final_dashboard_*.json` 作为处理前的 `source`；教学页仅读取原始视频帧，再由当前模型产生新的框、置信度和 Track ID。

- **原始画面**：只读取视频帧，不加载 YOLO。
- **YOLO 检测**：真实调用 `rpi_app/vision/detector.py` 的 `PersonDetector.detect()`，每帧独立输出 person 边界框和置信度。
- **YOLO + ByteTrack**：真实调用 `rpi_app/vision/tracker.py` 的 `PersonTracker.track()`；该封装内部完成 YOLO person 检测和 `model.track(..., persist=True)`，输出边界框、置信度、Track ID 和底部中心点。

检测与追踪是两条不同的真实 API 入口，教学台不会把 `PersonDetector.detect()` 的结果再交给 `PersonTracker.track()`。模型路径、`confidence` 和 `tracker` 都读取 `rpi_app/config.json`；模型只在第一次进入检测/追踪模式时加载，找不到模型时会提示且**不会自动下载**。

使用“上一帧 / 下一帧 / 播放 / 拖动进度条”观察过程。进入追踪模式后，换视频、切换模式、回退或不连续跳转都会重置 ByteTrack；因此 Track ID 可能重新编号，且 Track ID 只代表当前连续视频段内的临时关联，**不是身份识别**。当前帧没有 person 时，结果表会明确清空，不显示上一帧残留数据。

页面把 OpenCV/YOLO 工作放入一个后台 worker，并以队列交回 Tk 主线程绘制；关闭窗口时会请求 worker 关闭视频资源。测试使用 fake video / fake model，不连接串口、不枚举 COM 口、不加载权重。
