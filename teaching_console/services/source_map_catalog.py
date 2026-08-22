"""Verified, navigation-friendly source facts for the teaching Source Map."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


OFFICIAL = "official"
COMPATIBLE = "compatible"
CANDIDATE = "candidate"
INACTIVE = "inactive"


@dataclass(frozen=True)
class SourceEntry:
    id: str
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
    status: str = OFFICIAL
    upstream: tuple[str, ...] = ()
    downstream: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    source_line: int = 1
    teaching_file: str = "待接入"
    question: str = ""
    summary: str = ""
    concepts: tuple[str, ...] = ()
    lesson_upstream: str = ""
    lesson_downstream: str = ""


def _e(*args, **kwargs) -> SourceEntry:
    return SourceEntry(*args, **kwargs)


ENGINEERING_ENTRIES = (
    _e("camera_frame", "rpi_app / sources", "摄像头 / 视频原始帧", "rpi_app/sources/picamera_source.py",
       "正式相机入口读取 Picamera2 帧并交给 TrackedFrameProcessor。离线视频入口在 video_runner.py。",
       "TrackedFrameProcessor", "run_picamera2_camera, run_tracked_video", "camera 或 video frame", "BGR frame、source_time",
       "source_type、camera.width/height/format", "单图入口是兼容链；正式视频/相机均进入跟踪处理器。", upstream=(), downstream=("yolo_detection", "bytetrack_tracking"), keywords=("摄像头", "画面", "frame", "Picamera2", "视频"), source_line=45),
    _e("yolo_detection", "rpi_app / vision", "YOLO person 检测", "rpi_app/vision/tracker.py",
       "正式视频链在 PersonTracker.track 中用 YOLO 只保留 person。PersonDetector 是单图兼容实现。",
       "PersonTracker；兼容：PersonDetector", "track；兼容：detect", "BGR frame、model_path", "person boxes、confidence",
       "model_path、confidence、classes=[0]、imgsz", "classes=[0] 表示只保留 COCO person；confidence 是过滤阈值。", upstream=("camera_frame",), downstream=("bytetrack_tracking",), keywords=("YOLO", "person", "检测", "Detection", "Bounding Box", "confidence"), source_line=11),
    _e("bytetrack_tracking", "rpi_app / vision", "ByteTrack 与 Track ID", "rpi_app/vision/tracker.py",
       "Ultralytics 的 model.track(persist=True) 连续关联目标；项目不自己实现 ByteTrack。",
       "PersonTracker", "track", "当前 BGR frame、检测结果", "bbox、track_id、anchor_x、anchor_y",
       "tracking.tracker=bytetrack.yaml、confidence", "Track ID 是视频内的轨迹编号，不是身份识别。", upstream=("camera_frame", "yolo_detection"), downstream=("people_flow", "trajectory_history"), keywords=("ByteTrack", "Track ID", "跟踪", "persist"), source_line=23),
    _e("trajectory_history", "rpi_app / vision", "按 Track ID 保存轨迹", "rpi_app/vision/trajectory.py",
       "为每个 Track ID 保存底部中心的归一化坐标历史，并及时清理过期轨迹。",
       "TrajectoryAnalyzer", "update", "tracks、frame shape、source_timestamp", "trail、dx、dy、speed、motion state",
       "trajectory_seconds、min_track_age_seconds、min_motion_distance_norm", "历史结构是 dict[track_id] 到 deque[(time,x,y)]。", upstream=("bytetrack_tracking", "prediction"), downstream=("motion_direction", "flow_groups"), keywords=("轨迹", "history", "deque", "Track ID", "坐标"), source_line=43),
    _e("motion_direction", "rpi_app / vision", "运动方向 Δx / Δy", "rpi_app/vision/trajectory.py",
       "从过去位置到当前位置计算 dx/dy、位移、atan2 heading 和静止/不确定状态。",
       "TrajectoryAnalyzer", "update", "历史坐标与当前锚点", "heading_angle、motion_state、speed_norm",
       "min_track_age_seconds、min_motion_distance_norm", "单帧位置没有方向；位移太小会归为 STATIONARY。", upstream=("trajectory_history",), downstream=("flow_groups",), keywords=("方向", "Δx", "Δy", "heading", "atan2", "静止"), source_line=79),
    _e("people_flow", "rpi_app / vision", "人数历史与增长", "rpi_app/vision/people_flow.py",
       "按 source_time 记录左右区域人数快照，生成总人数与近期增长。", "PeopleFlowAnalyzer, FlowTrend", "update", "每帧左右人数、source time", "history、total_people、occupancy_growth", "flow_window_seconds、snapshot_interval_seconds", "区域统计是人数/增长历史，不是运动方向判定。", upstream=("bytetrack_tracking",), downstream=("prediction",), keywords=("人数", "人流", "history", "source_time", "增长"), source_line=19),
    _e("flow_groups", "rpi_app / ui", "方向相近的人流分组", "rpi_app/ui/flow_group_visualizer.py",
       "将正在运动、方向相近且位置相近的目标组织成可视化流组，也作为风险分析输入。", "—", "build_flow_groups", "motions_by_id", "flow_groups", "分组角度/距离条件", "分组辅助判断空间汇合；不能把不同方向直接等同于危险。", upstream=("trajectory_history", "motion_direction"), downstream=("flow_risk",), keywords=("flow group", "motion group", "方向", "人流"), source_line=23),
    _e("flow_risk", "rpi_app / decision", "正式空间汇合风险", "rpi_app/decision/flow_analysis.py",
       "依据不同流组质心的相对运动、人数和稳定条件判断空间上是否正在靠近。",
       "FlowRiskAnalyzer", "analyze, _pair_evidence", "motions、forecast、flow_groups", "convergence_score、risk、ETA、point",
       "flow_risk.*", "方向不同不等于危险；普通人流风险最终为 CROWD，不是 DANGER。", upstream=("flow_groups", "prediction"), downstream=("crowd_index",), keywords=("Flow Risk", "空间汇合", "convergence", "人流分组", "CROWD"), source_line=22),
    _e("crowd_index", "rpi_app / decision", "Crowd Index 三分量融合", "rpi_app/decision/crowd_index.py",
       "融合密度、近期增长和空间汇合分量，形成项目定义的拥挤风险指标。",
       "—", "calculate_crowd_index", "左右人数、增长率、convergence_score", "density_score、growth_score、conflict_score、crowd_index",
       "crowd_index.weight_density/weight_growth/weight_conflict", "不是神经网络置信度，也不是事故概率；真实权重由当前配置读取。", upstream=("flow_risk",), downstream=("vision_risk",), keywords=("Crowd Index", "密度", "增长", "权重", "风险"), source_line=8),
    _e("prediction", "rpi_app / decision", "15 秒历史与 10/20/30 秒趋势", "rpi_app/decision/crowd_predictor.py",
       "对 PeopleFlowAnalyzer 的历史做线性拟合，外推短时人数趋势。",
       "CrowdPredictor", "predict", "人数历史、current people", "prediction_slope、prediction_10/20/30、time_to_danger",
       "prediction.window_seconds、min_samples、min_history_seconds、horizons", "这是人数趋势外推，不是事故预测；time_to_danger 需校准阈值。", upstream=("people_flow",), downstream=("trajectory_history", "flow_risk"), keywords=("预测", "15 秒", "slope", "+10", "+20", "+30", "time_to_danger"), source_line=9),
    _e("vision_risk", "rpi_app / decision", "视觉风险状态融合", "rpi_app/decision/risk_engine.py",
       "将 Crowd Index 与正式人流风险映射为视觉状态；普通拥挤和空间汇合均使用 CROWD。", "RiskEngine", "evaluate, risk_from_crowd_index", "crowd_index、flow risk", "NORMAL/WARNING/CROWD", "crowd_index、flow_risk", "DANGER 是火警状态语义，不由普通人流链产生。", upstream=("crowd_index",), downstream=("uart_json",), keywords=("风险", "NORMAL", "WARNING", "CROWD", "DANGER")),
    _e("uart_json", "rpi_app / communication", "Pi ↔ ESP32 UART / JSON", "rpi_app/communication/esp32.py",
       "Pi 编码正式视觉 JSON 并按行轮询 ESP32 status 回传。", "ESP32Publisher, Esp32Status",
       "build_uart_payload, encode_uart_message, send_status, poll_esp32_status", "vision status、serial bytes", "换行 JSON、esp32_status",
       "esp32.port、baud、send_interval_seconds、receive_status", "生产串口为 115200 8N1；字段以此代码为唯一事实。", upstream=("vision_risk",), downstream=("esp32_firmware",), keywords=("UART", "JSON", "TX", "RX", "115200", "ESP32"), source_line=66),
    _e("esp32_firmware", "esp32_firmware", "ESP32 正式固件、传感器与执行器", "esp32_firmware/huian_esp32/huian_esp32.ino",
       "唯一正式 Arduino 草图：UART2/USB 输入同进 JSON 解析，融合 MQ-2、DHT11，控制 RGB/蜂鸣器，并双路回传状态。",
       "VisionData, SensorData", "parseVisionJson, updateSensors, overallSystemState, updateBuzzer, printAndSendStatus", "Pi UART2/USB JSON、MQ-2、DHT11", "RGB、蜂鸣器、esp32_status",
       "RX16/TX17、GPIO、MQ-2/DHT11 阈值", "NORMAL绿静音；WARNING蓝慢鸣；CROWD黄闪快鸣；DANGER/FIRE红闪长鸣；超时紫闪静音。", upstream=("uart_json",), downstream=("validation",), keywords=("MQ-2", "DHT11", "RGB", "蜂鸣器", "FIRE", "CROWD", "esp32_status", "USB", "UART2"), source_line=305),
    _e("validation", "validation", "Ground Truth 与 MAE 验证", "validation/scripts/validate.py",
       "按 source_time 将系统 status 与人工标注对比；教学台还有 SQLite Ground Truth 工作流。", "—",
       "validate_count, validate_prediction, validate_alarm, validate_direction", "status.jsonl、CSV Ground Truth", "MAE、最大误差、方向/预警对比",
       "tolerance_seconds", "没有标注就没有准确率；不得伪造结果。", upstream=("esp32_firmware",), downstream=(), keywords=("Ground Truth", "MAE", "验证", "方向", "预测", "人工标注"), source_line=37),
    _e("esp32_candidate", "审计 / inactive", "ESP32 模块化候选实现（未接线）", "esp32_firmware/huian_esp32/src/",
       "未被正式 .ino include 的候选模块实现。", "VisionState 等", "uart_protocol 等", "—", "—", "src/config.h",
       "不能作为正式运行代码讲解。", INACTIVE, keywords=("candidate", "inactive", "ESP32")),
)

_BY_ID = {entry.id: entry for entry in ENGINEERING_ENTRIES}
_LESSON_SOURCES = {
    "camera": "camera_frame", "detector": "yolo_detection", "tracker": "bytetrack_tracking", "trajectory": "trajectory_history",
    "flow_groups": "motion_direction", "people_flow": "people_flow", "flow_risk": "flow_risk", "crowd_index": "crowd_index",
    "prediction": "prediction", "risk": "crowd_index", "uart": "uart_json", "esp32_sensors": "esp32_firmware",
    "esp32_firmware": "esp32_firmware", "esp32_status": "esp32_firmware", "dashboard": "uart_json", "validation": "validation",
}


def engineering_entries(_root: Path | None = None) -> tuple[SourceEntry, ...]:
    return ENGINEERING_ENTRIES


def teaching_entries(_root: Path | None = None) -> tuple[SourceEntry, ...]:
    from teaching_console.services.source_map_nodes import LESSON_GROUPS
    from teaching_console.services.source_map_lessons import LESSON_DETAILS

    items: list[SourceEntry] = []
    for category, old_source, titles in LESSON_GROUPS:
        source = _BY_ID[_LESSON_SOURCES[old_source]]
        section = category.split(maxsplit=1)[0]
        for index, title in enumerate(titles, start=1):
            lesson = LESSON_DETAILS.get((section, index), {})
            concepts = lesson.get("concepts", tuple(dict.fromkeys((*source.keywords[:4], title))))
            question = lesson.get("question", f"{title}要解决什么问题？")
            summary = lesson.get("summary", f"本节单独理解“{title}”，再连接到正式工程模块。")
            items.append(SourceEntry(
                id=f"lesson.{section}.{index}", category=category, title=title, path=source.path,
                role=summary, classes=source.classes, functions=source.functions,
                inputs=lesson.get("inputs", source.inputs), outputs=lesson.get("outputs", source.outputs),
                config=lesson.get("config", source.config), note=lesson.get("note", source.note), status=source.status,
                upstream=source.upstream, downstream=source.downstream,
                keywords=tuple(dict.fromkeys((*concepts, category, title))), source_line=source.source_line,
                teaching_file=lesson.get("teaching_file", "待接入"), question=question, summary=summary,
                concepts=concepts, lesson_upstream=lesson.get("lesson_upstream", ""),
                lesson_downstream=lesson.get("lesson_downstream", ""),
            ))
    return tuple(items)

def all_entries(root: Path | None = None) -> tuple[SourceEntry, ...]:
    return (*teaching_entries(root), *engineering_entries(root))


def source_entries(root: Path | None = None) -> tuple[SourceEntry, ...]:
    return engineering_entries(root)


def search_entries(root: Path | None, query: str, *, teaching: bool | None = None) -> tuple[SourceEntry, ...]:
    needle = query.strip().casefold()
    entries = teaching_entries(root) if teaching is True else engineering_entries(root) if teaching is False else all_entries(root)
    if not needle:
        return entries
    return tuple(entry for entry in entries if needle in " ".join((entry.id, entry.title, entry.path, entry.role, entry.note, *entry.keywords)).casefold())


def entry_exists(root: Path, entry: SourceEntry) -> bool:
    return (Path(root) / entry.path).exists()
