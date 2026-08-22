# 依赖与平台矩阵

| 组件 | 必需运行环境 | 平台专用依赖 |
| --- | --- | --- |
| `rpi_app` 视频模式 | Python、Ultralytics、PyTorch、OpenCV、NumPy、Pillow | 无 |
| `rpi_app` Pi 摄像头模式 | 上述核心依赖 | `picamera2`、Pi CSI/IMX219 |
| `rpi_app` 实体 UART | 上述核心依赖 | `pyserial`、Pi UART 或 Windows COM |
| `teaching_console` | Python、Tkinter、OpenCV、Pillow | 可选 `pyserial`；YOLO 页需 Ultralytics/PyTorch |
| `esp32_firmware` | Arduino C++、ArduinoJson | ESP32、MQ-2、DHT11、RGB 灯、蜂鸣器 |
| `training` | Google Colab / GPU Python | Ultralytics、数据集与 CUDA 环境 |

历史 K230 和 PC 原型已外移至项目同级 `Huian_YOLO_Archive/`，不属于正式部署环境。