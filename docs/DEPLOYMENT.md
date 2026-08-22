# 运行与部署

## Windows 开发/演示

在项目根目录：

```powershell
python -m rpi_app.runners.video_demo --video test_data/000327.mp4 --no-esp32
python -m teaching_console.main
```

默认 Windows video demo 不枚举或打开串口。需要 USB 硬件演示时才显式指定 `--serial-port COM6`（或实际 COM 端口）。

## Raspberry Pi 5

部署目录为 `/home/x/Huian_YOLO`。安装核心 Python 依赖（Ultralytics、PyTorch、OpenCV、NumPy、Pillow、pyserial）及 Pi 专用 `picamera2`，保持模型位于 `/home/x/Huian_YOLO/models/`，然后执行：

```bash
cd /home/x/Huian_YOLO
source .venv/bin/activate
python -m rpi_app.main --config rpi_app/configs/rpi_imx219_live.json
```

Pi UART 使用配置中的 `/dev/ttyAMA0`。只有确认硬件接线后才设置 `esp32.enabled=true`、`dry_run=false`。

## Windows 发布包

当前可运行发布包位于项目同级 `Huian_YOLO_Releases/慧安楼道教学调试台/`。它是可再生成产物，不纳入源代码；重新打包使用项目根 `慧安楼道教学调试台.spec`。EXE 运行后，用户生成的数据库、导出和模型实验数据写入 EXE 同级 `huian_teaching_data/`。

## 资源与输出

- 原始视频：`test_data/`
- 模型：`models/`
- 运行输出：`output/`
- Ground Truth / 模板：`validation/`
- 历史材料与比赛成品：项目同级 `Huian_YOLO_Archive/`（正式代码不依赖）

不要把 `Huian_YOLO_Archive/final_dashboard_videos/` 的渲染成品作为 YOLO 输入。