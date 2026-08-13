# Dependency matrix

| Component | Allowed runtime | Not used |
| --- | --- | --- |
| `pc_prototype` | Python, Ultralytics, PyTorch, OpenCV | — |
| `k230_app` | CanMV MicroPython, camera, KPU, UART | torch, ultralytics, `cv2.VideoCapture` |
| `esp32_firmware` | Arduino C++, ArduinoJson | Python runtime |

K230 camera/KPU initialization remains pending the exact board model and CanMV firmware version.
