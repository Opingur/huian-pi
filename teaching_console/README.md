# 慧安楼道教学与调试台

独立 Windows Tkinter 教学工具，直接调用 `rpi_app/` 正式算法，不复制 YOLO、ByteTrack、Crowd Index 或预测实现。

## 启动

```powershell
python -m teaching_console.main
```

EXE 版本用户数据保存到 EXE 同级 `huian_teaching_data/`；源码版本保存在当前项目目录。两种模式都不使用 PyInstaller 临时目录。

## 当前模块

- 系统总览、源码地图与源码打开。
- YOLO / ByteTrack：四个原始教学案例、逐帧播放与真实检测/Track ID。
- 轨迹 / Direction、趋势 / Crowd Index、跑动事件解释。
- Ground Truth：人数、预测、方向等人工标注、SQLite、CSV/JSON 导出和统计。
- ESP32 实验：正式 UART JSON 的 USB 串口发送、状态镜像回传和四种教学状态。
- 模型优化 / YOLO Fine-tune：数据集、Colab 包、模型导入、A/B 与部署记录。

四个教学案例只读取 `test_data/` 中的原始视频；项目同级 `Huian_YOLO_Archive/final_dashboard_videos/` 中的渲染成品绝不会作为 YOLO 输入。

## 状态语义

| `vision_risk` | 含义 | 硬件响应 |
| --- | --- | --- |
| `NORMAL` | 正常 | 绿灯常亮、蜂鸣器静音 |
| `WARNING` | 一般预警 | 蓝灯常亮、约 2.2 秒一次短鸣 |
| `CROWD` | 拥挤报警 | 黄灯闪烁、快速连续短鸣 |
| `DANGER` | 火警 | 红灯快速闪烁、持续长鸣 |

`FIRE` 是 ESP32 本地确认火情的独立内部状态；它与 `DANGER` 使用相同的红灯/持续蜂鸣响应。