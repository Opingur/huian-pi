"""Verified teaching and engineering nodes for the Source Map.

The lesson wording is deliberately static, while every official path is checked
against the live repository by the UI and tests.  This keeps classroom language
stable without pretending that a missing file is runnable code.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


STATUS_OFFICIAL = "official"
STATUS_COMPATIBLE = "compatible"
STATUS_CANDIDATE = "candidate"
STATUS_INACTIVE = "inactive"


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
    status: str = STATUS_OFFICIAL
    upstream: tuple[str, ...] = ()
    downstream: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    question: str = ""
    summary: str = ""
    concepts: tuple[str, ...] = ()
    teaching_file: str = "待接入"
    lesson: str = ""
    source_line: int = 1


def _entry(*args, **kwargs) -> SourceEntry:
    return SourceEntry(*args, **kwargs)


ENGINEERING_ENTRIES: tuple[SourceEntry, ...] = (
    _entry("camera", "rpi_app / sources", "摄像头输入源", "rpi_app/sources/picamera_source.py", "Picamera2 延迟导入并提供 BGR 图像帧与 source_time。", "PicameraSource", "start, read, close", "Picamera2 frame", "BGR frame、source_time", "camera.width、camera.height、camera.format", "正式树莓派摄像头入口。", upstream=(), downstream=("tracker",), keywords=("摄像头", "frame", "Picamera2"), lesson="D1", source_line=45),
    _entry("detector", "rpi_app / vision", "图片单帧 person 检测（兼容）", "rpi_app/vision/detector.py", "图片模式的单帧 PersonDetector；不是视频主链的前置步骤。", "PersonDetector", "__init__, detect", "model_path、confidence、BGR frame", "person detection boxes", "model_path、confidence、classes=[0]", "视频/摄像头正式链使用 PersonTracker.track。", STATUS_COMPATIBLE, upstream=("camera",), downstream=("tracker",), keywords=("YOLO", "person", "Detection", "Bounding Box", "confidence"), lesson="D1", source_line=11),
    _entry("tracker", "rpi_app / vision", "视频 YOLO + ByteTrack", "rpi_app/vision/tracker.py", "一次 model.track 调用完成 person 检测和 ByteTrack 关联。", "PersonTracker", "__init__, track", "模型、BGR frame", "person boxes、Track ID、bottom-center anchor", "confidence、tracking.tracker、imgsz、classes=[0]", "Track ID 是当前连续视频段的目标/轨迹编号，不是身份识别。", upstream=("camera", "detector"), downstream=("trajectory",), keywords=("YOLO", "ByteTrack", "Track ID", "person", "persist"), lesson="D2", source_line=11),
    _entry("trajectory", "rpi_app / vision", "轨迹与方向", "rpi_app/vision/trajectory.py", "按 Track ID 保存底部中心归一化坐标历史，并从过去点到当前点得到运动状态和方向。", "TrajectoryAnalyzer", "update", "tracks、frame shape、source_timestamp、Conflict Zone", "motion_state、heading_angle、trail、speed", "trajectory_seconds、min_track_age_seconds、min_motion_distance_norm", "Conflict Zone 用于单目标距离/ETA，不是正式空间汇合评分输入。", upstream=("tracker",), downstream=("flow_risk", "flow_groups"), keywords=("轨迹", "方向", "Δx", "Δy", "heading", "Track ID"), lesson="D2-D3", source_line=43),
    _entry("flow_groups", "rpi_app / ui", "人流分组（辅助可视化）", "rpi_app/ui/flow_group_visualizer.py", "把 MOVING 的方向相近、位置相近目标显示为 flow group。", "—", "build_flow_groups", "motions_by_id", "flow_groups", "—", "用于正式 FlowRiskAnalyzer 的输入，也用于教学可视化。", upstream=("trajectory",), downstream=("flow_risk",), keywords=("人流", "flow group", "方向"), lesson="D3"),
    _entry("people_flow", "rpi_app / vision", "区域人数历史", "rpi_app/vision/people_flow.py", "固定区域的左右人数快照历史与增长率。", "PeopleFlowAnalyzer, FlowTrend", "update", "left_people、right_people、source timestamp", "history、total_people、growth", "flow_window_seconds、snapshot_interval_seconds", "兼容/辅助统计；不是正式方向判定依据。", STATUS_COMPATIBLE, upstream=("tracker",), downstream=("prediction", "crowd_index"), keywords=("人数", "区域", "history", "source_time"), lesson="D4"),
    _entry("flow_risk", "rpi_app / decision", "正式空间汇合风险", "rpi_app/decision/flow_analysis.py", "以不同流组质心的相对运动、人数与稳定条件判断是否在空间上靠近。", "FlowRiskAnalyzer", "analyze, _pair_evidence", "motions、forecast、flow_groups", "convergence_score、risk、ETA、point", "flow_risk", "两个方向不等于危险；正式 convergence_score 不直接读取 Conflict Zone。", upstream=("trajectory", "flow_groups", "prediction"), downstream=("crowd_index", "risk"), keywords=("Flow Risk", "空间汇合", "convergence", "风险"), lesson="D3-D4", source_line=22),
    _entry("crowd_index", "rpi_app / decision", "Crowd Index", "rpi_app/decision/crowd_index.py", "融合密度、近期增长与空间汇合风险的项目定义指标。", "—", "calculate_crowd_index", "左右人数、增长率、convergence_score", "density_score、growth_score、conflict_score、crowd_index", "crowd_index.weight_density/weight_growth/weight_conflict", "不是神经网络置信度，也不是事故概率；权重以当前 config.json 为准。", upstream=("people_flow", "flow_risk"), downstream=("risk",), keywords=("Crowd Index", "密度", "增长", "权重"), lesson="D4", source_line=8),
    _entry("prediction", "rpi_app / decision", "短时人数趋势", "rpi_app/decision/crowd_predictor.py", "使用最近历史做线性趋势拟合，外推 10/20/30 秒人数。", "CrowdPredictor", "predict", "PeopleFlow history、current people", "prediction_slope、prediction_10/20/30、time_to_danger", "prediction.window_seconds、min_samples、min_history_seconds、horizons", "是短时人数趋势外推，不是事故预测；time_to_danger 中文为预计达到危险人数阈值。", upstream=("people_flow",), downstream=("flow_risk", "risk"), keywords=("预测", "slope", "+10", "+20", "+30", "time_to_danger"), lesson="D4", source_line=9),
    _entry("risk", "rpi_app / decision", "视觉风险状态", "rpi_app/decision/risk_engine.py", "把 Crowd Index 阈值转换为视觉风险；人流相关风险统一使用 CROWD。", "RiskEngine", "risk_from_crowd_index, evaluate", "crowd_index、flow metrics", "NORMAL/WARNING/CROWD", "crowd_index、flow_risk", "DANGER 在最终产品语义中专门表示火警，不由普通拥挤产生。", upstream=("crowd_index", "flow_risk", "prediction"), downstream=("uart",), keywords=("风险", "NORMAL", "WARNING", "CROWD", "DANGER"), lesson="D4"),
    _entry("uart", "rpi_app / communication", "Pi ↔ ESP32 双向 UART JSON", "rpi_app/communication/esp32.py", "编码 Pi 正式视觉 JSON，并按行读取 ESP32 status JSON。", "ESP32Publisher, Esp32Status", "build_uart_payload, encode_uart_message, poll_esp32_status", "vision status、serial bytes", "Pi payload、esp32_status", "esp32.port、baud、send_interval_seconds、receive_status", "115200 8N1、共地；协议字段以此正式代码为准。", upstream=("risk",), downstream=("esp32_firmware", "dashboard"), keywords=("UART", "JSON", "TX", "RX", "115200", "ESP32"), lesson="D6", source_line=51),
    _entry("esp32_sensors", "esp32_firmware", "ESP32 传感器读取", "esp32_firmware/huian_esp32/huian_esp32.ino", "正式草图读取 MQ-2 AO 与 DHT11，并检查数据有效性。", "SensorData", "updateSensors", "MQ-2 ADC、DHT11", "mq2_value、temperature、warning", "MQ2_PIN=34、DHT_PIN=4、阈值/采样次数", "MQ-2 ADC 原始值不等于标准 ppm。", upstream=(), downstream=("esp32_firmware",), keywords=("MQ-2", "AO", "ADC", "DHT11", "温度"), lesson="D5", source_line=62),
    _entry("esp32_firmware", "esp32_firmware", "ESP32 正式状态机与执行器", "esp32_firmware/huian_esp32/huian_esp32.ino", "唯一正式 Arduino 上传入口：融合视觉与传感器状态，控制 RGB 与蜂鸣器。", "VisionData, SensorData", "parseVisionJson, stateRank, overallSystemState, wantedBuzzerMode, updateBuzzer", "Pi UART2/USB JSON、MQ-2、DHT11", "RGB、buzzer、esp32_status", "RX16/TX17、GPIO、MQ-2/DHT11 阈值", "NORMAL绿灯静音；WARNING蓝灯慢鸣；CROWD黄闪快鸣；DANGER/FIRE红闪长鸣；COMM_TIMEOUT紫闪静音。", upstream=("uart", "esp32_sensors"), downstream=("esp32_status",), keywords=("RGB", "蜂鸣器", "NORMAL", "CROWD", "FIRE", "COMM_TIMEOUT"), lesson="D5-D6", source_line=305),
    _entry("esp32_status", "esp32_firmware", "ESP32 状态回传", "esp32_firmware/huian_esp32/huian_esp32.ino", "正式草图将 esp32_status 同时写向 PiSerial 与 USB Serial。", "—", "printAndSendStatus", "SensorData、system state", "esp32_status JSON", "UART2 / USB 115200", "USB 既可输入课堂 JSON，也显示回传；PiSerial 是生产链路。", upstream=("esp32_firmware",), downstream=("uart", "dashboard"), keywords=("esp32_status", "回传", "timeout", "UART"), lesson="D6", source_line=1447),
    _entry("dashboard", "rpi_app / ui", "Dashboard 与日志", "rpi_app/vision/video_runner.py", "TrackedFrameProcessor 汇总状态、保存 status.jsonl，并在快照时发送 UART。", "TrackedFrameProcessor", "_analyse_tracks, process_frame, process_live_frame", "tracks、source_timestamp、ESP32 status", "status、dashboard/log input", "display、snapshot_interval_seconds", "source_time 来自视频时间或实时单调时间，不以 wall clock 作为视频证据。", upstream=("uart", "esp32_status"), downstream=("validation",), keywords=("Dashboard", "Log", "status.jsonl", "source_time"), lesson="D6-D7", source_line=61),
    _entry("validation", "validation", "人工验证工具链", "validation/scripts/validate.py", "把人工标注与导出的 status 记录按 source_time 对比。", "—", "validate_count, validate_prediction, validate_alarm, validate_direction", "CSV Ground Truth、status.jsonl", "MAE、最大误差、方向/预警对比", "tolerance=1.1 秒", "仓库模板没有真实结果时必须显示“未测试”，不能伪造准确率。", upstream=("dashboard",), downstream=(), keywords=("Ground Truth", "MAE", "方向", "验证", "预测"), lesson="D7", source_line=37),
    _entry("esp32_candidate", "esp32_firmware", "候选模块化实现（inactive）", "esp32_firmware/huian_esp32/src/", "另一套未被正式 .ino include 的候选模块。", "VisionState 等", "uart_protocol 等", "—", "—", "src/config.h", "当前未接入正式草图，不能当作正式运行实现讲解。", STATUS_INACTIVE, keywords=("candidate", "inactive", "ESP32"), lesson=""),
)


LESSON_GROUPS = (
    ("01 机器怎样获得画面", "camera", ("01.1 打开电脑摄像头", "01.2 读取一帧画面", "01.3 显示实时画面", "01.4 保存一张图片", "01.5 图片的宽、高、通道是什么", "01.6 正式树莓派摄像头入口")),
    ("02 YOLO 怎样找到人", "detector", ("02.1 加载 YOLO 模型", "02.2 把一张图片交给模型", "02.3 Detection 是什么", "02.4 Bounding Box 从哪里来", "02.5 class / person 是什么", "02.6 confidence 是什么", "02.7 为什么只保留 person", "02.8 一张图片中的人数怎样得到", "02.9 视频每一帧怎样执行检测", "02.10 检测结果怎样交给 ByteTrack")),
    ("03 ByteTrack 怎样连续跟踪", "tracker", ("03.1 为什么只有 YOLO 还不够", "03.2 每一帧都会重新检测", "03.3 什么是 Track ID", "03.4 Track ID 不是人员身份", "03.5 当前帧怎样和历史目标关联", "03.6 目标暂时丢失怎么办", "03.7 Track 结果包含什么", "03.8 Track 结果怎样交给轨迹模块")),
    ("04 轨迹怎样形成", "trajectory", ("04.1 人物框中心点怎样得到", "04.2 为什么保存历史位置", "04.3 一个目标有哪些历史坐标", "04.4 历史点怎样画成轨迹", "04.5 轨迹历史什么时候清理", "04.6 轨迹结果交给谁")),
    ("05 运动方向怎样判断", "trajectory", ("05.1 单帧位置为什么不能表示方向", "05.2 过去位置", "05.3 当前位置", "05.4 Δx / Δy 是什么", "05.5 位移怎样转换成方向", "05.6 静止目标怎样处理", "05.7 方向结果怎样显示", "05.8 方向结果怎样进入后续风险分析")),
    ("06 怎样统计人数与人流", "people_flow", ("06.1 total_people", "06.2 区域统计", "06.3 flow group", "06.4 motion group", "06.5 兼容统计和正式方向判断的区别")),
    ("07 怎样判断空间汇合风险", "flow_risk", ("07.1 什么是不同人流", "07.2 方向不同不等于危险", "07.3 什么叫空间上正在靠近", "07.4 什么叫汇合区域", "07.5 人数条件", "07.6 持续时间 / 稳定条件", "07.7 Flow Risk 输出给 Crowd Index 什么")),
    ("08 怎样计算 Crowd Index", "crowd_index", ("08.1 人员密度分量", "08.2 近期增长风险分量", "08.3 空间风险分量", "08.4 权重从哪里读取", "08.5 三个分量怎样合成", "08.6 Crowd Index 怎样对应风险状态", "08.7 Crowd Index 不是什么")),
    ("09 怎样记录人数历史", "people_flow", ("09.1 每个时刻记录什么", "09.2 source_time 是什么", "09.3 为什么不用 wall clock", "09.4 历史窗口多长", "09.5 数据什么时候足够", "09.6 历史数据交给 Prediction 什么")),
    ("10 怎样得到短时人数趋势", "prediction", ("10.1 最近历史人数", "10.2 人数趋势 slope", "10.3 线性拟合做什么", "10.4 +10 秒人数", "10.5 +20 秒人数", "10.6 +30 秒人数", "10.7 prediction_valid", "10.8 数据不足时不能预测", "10.9 time_to_danger", "10.10 为什么这不是事故预测")),
    ("11 树莓派怎样把结果发给 ESP32", "uart", ("11.1 为什么需要 ESP32", "11.2 UART 是什么", "11.3 TX / RX", "11.4 为什么需要共地", "11.5 115200 8N1", "11.6 JSON 是什么", "11.7 Pi → ESP32 当前正式字段", "11.8 一条 JSON 怎样发送", "11.9 ESP32 收到以后交给谁")),
    ("12 ESP32 怎样读取传感器", "esp32_sensors", ("12.1 MQ-2 是什么", "12.2 MQ-2 AO", "12.3 为什么需要分压", "12.4 ESP32 ADC", "12.5 DHT11", "12.6 温度数据", "12.7 传感器数据有效性", "12.8 传感器数据交给风险融合")),
    ("13 ESP32 怎样控制灯和蜂鸣器", "esp32_firmware", ("13.1 状态怎样决定 RGB", "13.2 NORMAL", "13.3 WARNING", "13.4 CROWD", "13.5 DANGER / FIRE", "13.6 COMM_TIMEOUT", "13.7 蜂鸣器模式")),
    ("14 ESP32 怎样把状态传回树莓派", "esp32_status", ("14.1 为什么需要回传", "14.2 ESP32 状态 JSON", "14.3 传感器值", "14.4 当前报警状态", "14.5 树莓派在哪里接收", "14.6 timeout 怎样判断", "14.7 Dashboard 怎样使用")),
    ("15 怎样验证系统到底准不准", "validation", ("15.1 Ground Truth 是什么", "15.2 人工人数标注", "15.3 系统人数输出", "15.4 MAE", "15.5 方向人工标注", "15.6 方向准确率", "15.7 +10/+20/+30 预测验证", "15.8 预警场景验证", "15.9 最大错误案例", "15.10 修改后怎样复测")),
    ("16 整个慧安楼道的数据怎样流动", "dashboard", ("16.1 摄像头到图像帧", "16.2 YOLO person detection", "16.3 ByteTrack", "16.4 Track history", "16.5 Trajectory / Direction", "16.6 Flow Risk", "16.7 Crowd Index", "16.8 Prediction", "16.9 UART JSON", "16.10 ESP32 与 Dashboard / Validation")),
)


def engineering_entries(_root: Path | None = None) -> tuple[SourceEntry, ...]:
    return ENGINEERING_ENTRIES


def teaching_entries(_root: Path | None = None) -> tuple[SourceEntry, ...]:
    base = {entry.id: entry for entry in ENGINEERING_ENTRIES}
    nodes: list[SourceEntry] = []
    for category, source_id, titles in LESSON_GROUPS:
        source = base[source_id]
        for number, title in enumerate(titles, start=1):
            nodes.append(SourceEntry(
                id=f"lesson.{source_id}.{number}", category=category, title=title, path=source.path,
                role=source.role, classes=source.classes, functions=source.functions, inputs=source.inputs,
                outputs=source.outputs, config=source.config, note=source.note, status=source.status,
                upstream=source.upstream, downstream=source.downstream,
                keywords=tuple(dict.fromkeys((*source.keywords, category, title))),
                question=f"{title}？", summary=source.role, concepts=source.keywords[:5],
                teaching_file="待接入", lesson=source.lesson, source_line=source.source_line,
            ))
    return tuple(nodes)


def all_entries(root: Path | None = None) -> tuple[SourceEntry, ...]:
    return (*teaching_entries(root), *engineering_entries(root))


def search_entries(root: Path | None, query: str, *, teaching: bool | None = None) -> tuple[SourceEntry, ...]:
    value = query.strip().casefold()
    entries = teaching_entries(root) if teaching is True else engineering_entries(root) if teaching is False else all_entries(root)
    if not value:
        return entries
    return tuple(entry for entry in entries if value in " ".join((entry.title, entry.question, entry.path, entry.role, entry.note, *entry.keywords)).casefold())


def entry_exists(root: Path, entry: SourceEntry) -> bool:
    return (Path(root) / entry.path).exists()
