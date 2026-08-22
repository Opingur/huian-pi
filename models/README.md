# 模型目录

- `yolov8n.pt`：正式 person 检测基线模型。
- `fire_n.pt`：正式视觉火焰模型。
- `yolov8n.onnx`：由维护工具导出的 ONNX 版本。
- `yolo11n.pt`：保留的未接入实验模型；当前正式配置不引用它。

模型统一保存在此目录。不要把模型副本放回项目根目录；教学台的候选微调模型写入其可写数据根的 `models/experiments/`。