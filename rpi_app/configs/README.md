# rpi_app 配置说明

- `../config.json`：通用默认配置；默认测试图为 `../test_data/images/bus.jpg`。
- `rpi_imx219_live.json`：Raspberry Pi 5 + IMX219 正式摄像头运行配置。
- `demo_000318.json`、`demo_000327.json`、`demo_000345_explain.json`：可复现实验案例。
- `final_dashboard_000318/327/345/353.json`：四个固定原始案例的 Dashboard 复现配置，输入均为项目内相对路径。
- `crossroad_test.json`、`fire_demo_01.json`：需要额外测试素材的专用模板；运行前须提供其 `source`。
- `demo_fire_image.json`：根 `test_data/images/fire_positive.jpg` 的图片验证。

所有相对路径由 `rpi_app/utils/config.py` 相对 `rpi_app/` 解析。输出必须使用 `../output/...`，不要重新在 `rpi_app/` 下创建输出目录。

含旧 Windows 绝对路径的配置已移至项目同级 `Huian_YOLO_Archive/old_configs/`，不参与正式运行。