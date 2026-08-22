"""Child-level classroom wording for the Source Map.

These descriptions deliberately separate a small lesson from the larger
production module it eventually points to.  The source map combines this
material with repository-verified paths in ``source_map_catalog``.
"""
from __future__ import annotations


PENDING = "待接入"
EXAMPLES = "teaching_examples/d1_camera_yolo/"


def detail(question, summary, concepts, teaching_file=PENDING, inputs="—", outputs="—", config="—", note="—", upstream="—", downstream="—"):
    return {
        "question": question, "summary": summary, "concepts": tuple(concepts),
        "teaching_file": teaching_file, "inputs": inputs, "outputs": outputs,
        "config": config, "note": note, "lesson_upstream": upstream,
        "lesson_downstream": downstream,
    }


LESSON_DETAILS = {
    ("01", 1): detail("怎样让 Python 打开电脑摄像头？", "OpenCV 用 VideoCapture 连接电脑摄像头，先确认它确实打开。", ("camera", "cv2.VideoCapture", "isOpened"), EXAMPLES + "01_open_camera.py", "电脑摄像头编号 0", "可读取的摄像头对象", "—", "打开摄像头不等于已经读到图片。", "—", "01.2 读取一帧画面"),
    ("01", 2): detail("摄像头怎样交给我们一张图片？", "camera.read() 会返回是否成功的 ok 和当前一帧 frame。", ("camera.read()", "ok", "frame"), EXAMPLES + "01_open_camera.py", "已打开的 camera", "ok、frame", "—", "先检查 ok，失败时不能把空 frame 当图片使用。", "01.1 打开电脑摄像头", "01.3 显示实时画面"),
    ("01", 3): detail("怎样把不断读到的 frame 显示成实时画面？", "循环读取 frame，再用 imshow 显示；waitKey 让窗口响应并可按键退出。", ("cv2.imshow", "cv2.waitKey", "loop", "frame"), EXAMPLES + "01_open_camera.py", "连续 frame", "实时窗口画面", "—", "imshow 不是摄像头，它只负责显示已经读到的图片。", "01.2 读取一帧画面", "01.4 保存一张图片"),
    ("01", 4): detail("怎样把当前画面保存成一张图片？", "cv2.imwrite 把当前 frame 写入一个图片文件，例如 capture.jpg。", ("cv2.imwrite", "capture.jpg", "frame"), EXAMPLES + "02_capture_photo.py", "一张 frame、保存路径", "磁盘上的图片文件", "—", "保存的是按下按键那一刻的 frame，不是连续视频文件。", "01.2 读取一帧画面", "01.5 图片的宽、高、通道是什么"),
    ("01", 5): detail("Python 得到一张图片以后，怎样知道它有多宽、多高，以及有几个颜色通道？", "OpenCV 的彩色图片通常是 NumPy 数组；image.shape 给出高度、宽度和颜色通道数。", ("image", "frame", "shape", "height", "width", "channels", "BGR", "pixel"), EXAMPLES + "03_frame_info.py", "一张 BGR 图像 / frame", "height、width、channels", "—", "shape 的顺序通常是 height、width、channels，不是 width 在前；本节没有独立的正式宽高通道模块。", "01.4 保存一张图片", "02 YOLO 怎样找到人"),
    ("01", 6): detail("慧安楼道的树莓派怎样获得正式摄像头画面？", "正式系统由 Picamera2 读取画面，转换后交给 TrackedFrameProcessor，并记录 source_time。", ("Picamera2", "PicameraSource", "TrackedFrameProcessor", "source_time"), PENDING, "Picamera2 capture_array()", "BGR frame、处理状态、snapshot", "source_type、camera.width、camera.height、camera.format", "这是树莓派正式工程入口，和前面的 OpenCV 最小实验分开。", "01.1～01.5 D1 教学实验", "YOLO / ByteTrack 正式处理链"),
    ("02", 1): detail("怎样加载 YOLO 模型？", "YOLO 会从 yolov8n.pt 文件创建模型对象，之后才能处理图片。", ("YOLO", "model", "yolov8n.pt"), EXAMPLES + "04_yolo_photo.py", "模型文件路径", "YOLO model 对象", "model_path", "加载模型不是开始跟踪，也不会自动打开摄像头。", "01.5 图片信息", "02.2 把一张图片交给模型"),
    ("02", 2): detail("怎样把一张图片交给 YOLO？", "把 image 作为 source 交给 model.predict，模型返回当前图片的结果。", ("model.predict", "source", "image", "result"), EXAMPLES + "04_yolo_photo.py", "YOLO model、image", "当前帧 result", "confidence、classes", "模型只回答当前一张图里发现了什么。", "02.1 加载 YOLO 模型", "02.3 Detection 是什么"),
    ("02", 3): detail("Detection 是什么？", "Detection 是模型在图片里发现的一个候选目标结果，里面会带位置、类别和置信度。", ("Detection", "candidate", "box", "class", "confidence"), EXAMPLES + "04_yolo_photo.py", "模型 result", "一个候选目标", "—", "Detection 不是人的身份证明，而是本帧的模型结果。", "02.2 把一张图片交给模型", "02.4 Bounding Box 从哪里来"),
    ("02", 4): detail("人物的 Bounding Box 从哪里来？", "模型结果中的 x1、y1、x2、y2 表示矩形左上和右下角。", ("Bounding Box", "x1", "y1", "x2", "y2"), EXAMPLES + "04_yolo_photo.py", "一个 Detection", "人物矩形框坐标", "—", "框是图片坐标，不是现实世界中人的真实大小。", "02.3 Detection 是什么", "02.5 class / person 是什么"),
    ("02", 5): detail("class / person 是什么？", "class 表示模型认为目标属于哪一类；person 是其中的人类别。", ("class", "person", "COCO", "类别"), EXAMPLES + "04_yolo_photo.py", "Detection class", "类别名称 / class id", "classes=[0]", "class 是模型类别，不是这个人的名字。", "02.4 Bounding Box 从哪里来", "02.6 confidence 是什么"),
    ("02", 6): detail("0.87 confidence 是什么？", "confidence 是模型对当前检测结果的置信程度，用来决定是否保留该检测框。", ("confidence", "threshold", "detection"), EXAMPLES + "04_yolo_photo.py", "Detection confidence", "是否保留该框", "confidence", "不是系统准确率、不是事故概率，也不是这个人有 87% 真实存在。", "02.5 class / person 是什么", "02.7 为什么只保留 person"),
    ("02", 7): detail("为什么慧安楼道只保留 person？", "教学和正式检测都只关心人，因此用 classes=[0] 过滤 person 类别。", ("classes=[0]", "person", "filter"), EXAMPLES + "04_yolo_photo.py", "全部模型检测结果", "只含 person 的检测框", "classes=[0]", "0 是当前 COCO person 类别编号，不是人数。", "02.6 confidence 是什么", "02.8 一张图片中的人数怎样得到"),
    ("02", 8): detail("一张图片中的人数怎样得到？", "保留下来的 person 检测框有几个，当前图片的系统人数就是几个。", ("person boxes", "len", "count"), EXAMPLES + "04_yolo_photo.py", "person 检测框列表", "当前系统人数", "classes=[0]、confidence", "这是系统检测人数，不是人工 Ground Truth。", "02.7 为什么只保留 person", "02.9 视频每一帧怎样执行检测"),
    ("02", 9): detail("视频每一帧怎样执行检测？", "摄像头不断产生 frame；YOLO 对每个当前 frame 再做一次检测。", ("video", "frame", "loop", "YOLO"), EXAMPLES + "05_yolo_camera.py", "连续 BGR frame", "每帧 person detections", "confidence、classes=[0]", "每一帧重新检测，不代表模型已经知道同一个人是谁。", "01.3 显示实时画面", "02.10 检测结果怎样交给 ByteTrack"),
    ("02", 10): detail("YOLO 的当前帧检测结果怎样交给 ByteTrack？", "YOLO 只知道这一帧有哪些人；正式 PersonTracker.track 让 ByteTrack 将相邻帧目标连续关联。", ("YOLO", "ByteTrack", "current frame", "association"), PENDING, "当前帧 person boxes", "带 Track ID 的 tracks", "tracking.tracker、persist=True", "不能把单帧 Detection 当成连续轨迹。", "02.9 视频每一帧怎样执行检测", "03 ByteTrack 怎样连续跟踪"),
    ("03", 1): detail("为什么只有 YOLO 还不够？", "YOLO 每帧只报告当前框；要画轨迹和方向，需要知道前后帧是否同一个目标。", ("YOLO", "tracking", "trajectory"), PENDING, "逐帧 detections", "连续 Track ID", "tracking.tracker", "检测和跟踪是两个不同问题。", "02.10 检测结果交给 ByteTrack", "03.2 每一帧都会重新检测"),
    ("03", 2): detail("每一帧都会重新检测吗？", "会。正式 track 调用仍对每帧做检测，再把本帧结果与历史轨迹关联。", ("frame", "detection", "association", "persist=True"), PENDING, "连续 frame", "本帧 detections 与 tracks", "persist=True", "persist 保存的是跟踪状态，不是跳过检测。", "03.1 为什么只有 YOLO 还不够", "03.3 什么是 Track ID"),
    ("03", 3): detail("什么是 Track ID？", "Track ID 是系统给当前连续轨迹的目标编号，方便把前后帧连起来。", ("Track ID", "目标编号", "轨迹编号"), PENDING, "连续检测框", "track_id", "ByteTrack", "Track ID 只在当前视频跟踪过程中有意义。", "03.2 每一帧都会重新检测", "03.4 Track ID 不是人员身份"),
    ("03", 4): detail("Track ID 是不是人员身份？", "不是。它只是当前视频里的目标编号 / 轨迹编号，不做人脸识别或身份确认。", ("Track ID", "轨迹编号", "不是身份"), PENDING, "track_id", "用于连接轨迹的编号", "—", "禁止把 Track ID 讲成姓名、身份证或身份识别。", "03.3 什么是 Track ID", "03.5 当前帧怎样和历史目标关联"),
    ("03", 5): detail("当前帧目标怎样和历史目标关联？", "ByteTrack 根据连续帧目标的位置和跟踪状态进行关联，正式实现由 Ultralytics 调用。", ("ByteTrack", "association", "history", "persist"), PENDING, "本帧 boxes、内部 tracker 状态", "持续的 track_id", "tracker=bytetrack.yaml、persist=True", "项目没有自己重写 ByteTrack 算法。", "03.4 Track ID 不是人员身份", "03.6 目标暂时丢失怎么办"),
    ("03", 6): detail("目标暂时丢失怎么办？", "跟踪器会按自己的规则短暂保留轨迹状态，之后若无法关联会结束该轨迹。", ("lost track", "tracker state", "association"), PENDING, "历史跟踪状态、后续检测", "继续或结束的轨迹", "bytetrack.yaml", "重新出现的人不保证得到原来的 Track ID。", "03.5 当前帧怎样和历史目标关联", "03.7 Track 结果包含什么"),
    ("03", 7): detail("Track 结果包含什么？", "正式系统输出人物框、confidence、track_id，以及用于轨迹的底部中心 anchor。", ("bbox", "confidence", "track_id", "anchor_x", "anchor_y"), PENDING, "PersonTracker.track 结果", "track 字典", "confidence、imgsz", "anchor 是画面坐标，不是人的真实脚部测量值。", "03.6 目标暂时丢失怎么办", "03.8 Track 结果怎样交给轨迹模块"),
    ("03", 8): detail("Track 结果怎样交给轨迹模块？", "TrackedFrameProcessor 把 tracks 和 source_time 交给 TrajectoryAnalyzer.update，形成历史轨迹。", ("tracks", "TrajectoryAnalyzer", "source_time", "history"), PENDING, "tracks、frame shape、source_time", "轨迹历史与方向数据", "trajectory_seconds", "轨迹模块保存的是位置历史，不是身份资料。", "03.7 Track 结果包含什么", "04 轨迹怎样形成"),
}
