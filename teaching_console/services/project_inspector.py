"""Live project inspection and source-map facts for teacher preparation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceEntry:
    category: str
    title: str
    path: str
    role: str
    classes: str
    functions: str
    inputs: str
    outputs: str
    config: str
    note: str


SOURCE_ENTRIES = (
    SourceEntry("YOLO / Tracking", "图片单帧 Person 检测", "rpi_app/vision/detector.py", "图片模式的旧单帧检测链；不是视频主链必经步骤。", "PersonDetector", "__init__, detect", "模型路径、置信度、图像帧", "person 框与置信度", "model_path, confidence；classes=[0]", "视频/摄像头应讲 PersonTracker.track。"),
    SourceEntry("YOLO / Tracking", "视频/摄像头 YOLO + ByteTrack", "rpi_app/vision/tracker.py", "Ultralytics 在同一次 track 调用中完成 person 检测与 ByteTrack。", "PersonTracker", "__init__, track", "模型、BGR 帧", "person 框、Track ID、底部锚点", "tracking.tracker=bytetrack.yaml；confidence；classes=[0]", "persist=True；项目不自行实现 ByteTrack。"),
    SourceEntry("Trajectory / Direction", "轨迹与画面运动方向", "rpi_app/vision/trajectory.py", "按 Track ID 保存最近约两秒的底部中心轨迹。", "TrajectoryAnalyzer", "update", "tracks、帧尺寸、时间、Conflict Zone", "heading、速度、轨迹、到区距离、ETA", "trajectory_seconds=2.0；min_track_age_seconds=0.8", "Conflict Zone 只用于单人接近关系和绘制。"),
    SourceEntry("Flow Risk", "正式空间汇合风险", "rpi_app/decision/flow_analysis.py", "按流组质心的相对运动评估空间汇合。", "FlowRiskAnalyzer", "analyze, _pair_evidence", "motions、预测、视觉分组", "convergence_score/risk/eta/point", "flow_risk", "正式 convergence_score 不直接读取 Conflict Zone。"),
    SourceEntry("Crowd Index", "拥挤指数", "rpi_app/decision/crowd_index.py", "将密度、增长和空间汇合分合成指数。", "—", "calculate_crowd_index", "左右人数、增长率、convergence_score", "density/growth/conflict/index", "权重 0.5 / 0.3 / 0.2", "当前 conflict_score 是 convergence_score，不是旧 direction_conflict。"),
    SourceEntry("Prediction", "短时人数趋势", "rpi_app/decision/crowd_predictor.py", "对固定区域占用历史做最小二乘趋势拟合。", "CrowdPredictor", "predict", "15 秒快照、当前人数", "slope、10/20/30 秒预测、ETA", "prediction.window_seconds=15", "未校准 danger_people_threshold 时 time_to_danger 为 null。"),
    SourceEntry("Raspberry Pi ↔ ESP32", "双向 UART JSON", "rpi_app/communication/esp32.py", "Pi 发送正式视觉载荷，并读取 ESP32 status。", "ESP32Publisher, Esp32Status", "build_uart_payload, send_status, poll_esp32_status", "内部 status、串口字节", "10 字段 Pi payload；esp32_status", "esp32.port/baud/interval/timeout", "v1 视觉 smoke 在 Pi 编码器中固定 false/0.0。"),
    SourceEntry("ESP32 Firmware", "正式 Arduino 草图", "esp32_firmware/huian_esp32/huian_esp32.ino", "唯一正式上传入口：Pi UART2 与 USB 输入同进 JSON 解析。", "VisionData, SensorData", "readJsonStream, parseVisionJson, printAndSendStatus", "PiSerial 或 USB JSON；传感器", "RGB/蜂鸣器控制；esp32_status", "115200；RX16/TX17", "状态语义：NORMAL绿灯静音、WARNING蓝灯慢鸣、CROWD黄闪快鸣、DANGER火警红闪长鸣；内部 FIRE 为独立确认火情。"),
    SourceEntry("ESP32 Firmware", "候选模块化实现（inactive）", "esp32_firmware/huian_esp32/src/", "未被正式 .ino 引入的另一套候选代码。", "VisionState 等", "uart_protocol 等", "—", "—", "src/config.h", "当前未接入正式 .ino / inactive，不应作为运行实现讲解。"),
    SourceEntry("Validation", "人工标注与对比", "validation/scripts/validate.py", "将 status.jsonl 与人工模板做离线比对。", "—", "validate_count/prediction/alarm/direction", "status.jsonl、CSV 标注", "MAE/命中率/方向对比", "默认时间容差 1.1 秒", "模板为空，仓库没有真实 Ground Truth 数据。"),
)


def source_entries(root: Path) -> tuple[SourceEntry, ...]:
    _ = root
    return SOURCE_ENTRIES


def entry_exists(root: Path, entry: SourceEntry) -> bool:
    return (root / entry.path).exists()
