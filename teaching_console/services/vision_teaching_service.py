"""Real project adapters for the YOLO / ByteTrack teaching page."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Any, Callable

MODE_RAW = "raw"
MODE_DETECT = "detect"
MODE_TRACK = "track"


class VisionTeachingError(RuntimeError):
    pass


@dataclass(frozen=True)
class VisionTeachingConfig:
    model_path: Path
    confidence: float
    tracker: str
    imgsz: int


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    total_frames: int
    fps: float
    width: int
    height: int


@dataclass(frozen=True)
class TeachingRow:
    index: int
    confidence: float
    bbox: tuple[int, int, int, int]
    track_id: int | None = None
    anchor: tuple[int, int] | None = None

    @property
    def bbox_text(self) -> str:
        return "({}, {}, {}, {})".format(*self.bbox)

    @property
    def anchor_text(self) -> str:
        return "—" if self.anchor is None else "({}, {})".format(*self.anchor)


@dataclass(frozen=True)
class FramePacket:
    frame_index: int
    video: VideoInfo
    mode: str
    frame_bgr: Any
    rows: tuple[TeachingRow, ...]
    tracker_reset: bool

    @property
    def seconds(self) -> float:
        return self.frame_index / self.video.fps if self.video.fps else 0.0


@dataclass(frozen=True)
class WorkerResult:
    token: int
    operation: str
    value: Any = None
    error: str | None = None


def load_vision_config(root: Path) -> VisionTeachingConfig:
    """Read rpi_app/config.json; this never imports or downloads YOLO."""
    config_path = Path(root) / "rpi_app" / "config.json"
    if not config_path.is_file():
        raise VisionTeachingError(f"找不到项目配置：{config_path}")
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VisionTeachingError(f"无法读取项目配置：{error}") from error
    if not data.get("model_path"):
        raise VisionTeachingError("rpi_app/config.json 缺少 model_path。")
    tracking = data.get("tracking", {})
    return VisionTeachingConfig(
        model_path=(config_path.parent / str(data["model_path"])).resolve(),
        confidence=float(data.get("confidence", 0.35)),
        tracker=str(tracking.get("tracker", "bytetrack.yaml")),
        imgsz=int(tracking.get("imgsz", 640)),
    )


# These are source inputs declared by the corresponding final_dashboard_*.json
# configurations.  They are deliberately not resolved from final_dashboard_videos/.
TEACHING_CASES: tuple[tuple[str, str, Path], ...] = (
    ("000318", "人数增长", Path("test_data/iitb_final/000318.mp4")),
    ("000327", "目标跟踪 / Track ID", Path("test_data/000327.mp4")),
    ("000345", "人数下降", Path("test_data/iitb_final/000345.mp4")),
    ("000353", "增长 / 趋势", Path("test_data/iitb_final/000353.mp4")),
)


def teaching_cases(root: Path) -> tuple[tuple[str, str, Path], ...]:
    """Return present raw inputs only; rendered dashboard videos are never candidates."""
    root = Path(root)
    return tuple((code, purpose, root / relative) for code, purpose, relative in TEACHING_CASES
                 if (root / relative).is_file())


def find_example_video(root: Path) -> Path | None:
    """Default to raw case 000327, then another available raw teaching case."""
    cases = teaching_cases(root)
    for code, _purpose, path in cases:
        if code == "000327":
            return path
    return cases[0][2] if cases else None


def rows_from_results(results: list[dict[str, Any]], tracking: bool) -> tuple[TeachingRow, ...]:
    rows: list[TeachingRow] = []
    for index, item in enumerate(results, start=1):
        bbox = tuple(int(item[key]) for key in ("x1", "y1", "x2", "y2"))
        track_id = int(item["track_id"]) if tracking and "track_id" in item else None
        anchor = None
        if tracking and "anchor_x" in item and "anchor_y" in item:
            anchor = (int(item["anchor_x"]), int(item["anchor_y"]))
        rows.append(TeachingRow(index, float(item.get("confidence", 0.0)), bbox, track_id, anchor))
    return tuple(rows)


class VisionTeachingService:
    """Serial owner for video capture and the real PersonDetector/PersonTracker wrappers."""

    def __init__(self, root: Path, *, cv2_loader: Callable[[], Any] | None = None,
                 detector_factory: Callable[[Path, float], Any] | None = None,
                 tracker_factory: Callable[[Path, float, str, int], Any] | None = None) -> None:
        self.root = Path(root)
        self.config = load_vision_config(self.root)
        self._cv2_loader = cv2_loader or self._load_cv2
        self._detector_factory = detector_factory or self._build_detector
        self._tracker_factory = tracker_factory or self._build_tracker
        self._cv2: Any | None = None
        self._capture: Any | None = None
        self._video: VideoInfo | None = None
        self._detector: Any | None = None
        self._tracker: Any | None = None
        self._last_tracking_frame: int | None = None

    @staticmethod
    def _load_cv2() -> Any:
        try:
            import cv2
        except ImportError as error:
            raise VisionTeachingError("缺少 OpenCV：请安装 opencv-python 后重试。") from error
        return cv2

    @staticmethod
    def _build_detector(model_path: Path, confidence: float) -> Any:
        try:
            from rpi_app.vision.detector import PersonDetector
        except ImportError as error:
            raise VisionTeachingError("无法导入项目 PersonDetector；请确认 ultralytics 依赖可用。") from error
        return PersonDetector(model_path, confidence)

    @staticmethod
    def _build_tracker(model_path: Path, confidence: float, tracker: str, imgsz: int) -> Any:
        try:
            from rpi_app.vision.tracker import PersonTracker
        except ImportError as error:
            raise VisionTeachingError("无法导入项目 PersonTracker；请确认 ultralytics 依赖可用。") from error
        return PersonTracker(model_path, confidence, tracker=tracker, imgsz=imgsz)

    def _get_cv2(self) -> Any:
        if self._cv2 is None:
            self._cv2 = self._cv2_loader()
        return self._cv2

    def _ensure_detector(self) -> Any:
        if self._detector is None:
            if not self.config.model_path.is_file():
                raise VisionTeachingError(f"找不到模型：{self.config.model_path}；不会自动下载。")
            self._detector = self._detector_factory(self.config.model_path, self.config.confidence)
        return self._detector

    def _ensure_tracker(self) -> Any:
        if self._tracker is None:
            if not self.config.model_path.is_file():
                raise VisionTeachingError(f"找不到模型：{self.config.model_path}；不会自动下载。")
            self._tracker = self._tracker_factory(self.config.model_path, self.config.confidence, self.config.tracker, self.config.imgsz)
        return self._tracker

    def reset_tracker(self) -> None:
        """Reset persist=True state after seek, backward, video change, or mode change."""
        self._tracker = None
        self._last_tracking_frame = None

    def reload_models(self) -> None:
        self._detector = None
        self.reset_tracker()

    def open_video(self, path: Path | str) -> VideoInfo:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise VisionTeachingError(f"找不到视频：{source}")
        cv2 = self._get_cv2()
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            capture.release()
            raise VisionTeachingError(f"无法打开视频：{source}")
        if self._capture is not None:
            self._capture.release()
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        self._video = VideoInfo(source, max(0, int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)), fps or 1.0,
                                int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0))
        self._capture = capture
        self.reset_tracker()
        return self._video

    def read_frame(self, frame_index: int, mode: str, sequential: bool = False) -> FramePacket:
        if mode not in {MODE_RAW, MODE_DETECT, MODE_TRACK}:
            raise VisionTeachingError(f"未知观察模式：{mode}")
        if self._capture is None or self._video is None or self._video.total_frames <= 0:
            raise VisionTeachingError("请先选择一个可读取的视频。")
        index = max(0, min(int(frame_index), self._video.total_frames - 1))
        tracker_reset = mode == MODE_TRACK and (not sequential or self._last_tracking_frame != index - 1)
        if tracker_reset:
            self.reset_tracker()
        cv2 = self._get_cv2()
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise VisionTeachingError(f"无法读取第 {index + 1} 帧。")
        rows: tuple[TeachingRow, ...] = ()
        if mode == MODE_DETECT:
            rows = rows_from_results(self._ensure_detector().detect(frame), False)
        elif mode == MODE_TRACK:
            rows = rows_from_results(self._ensure_tracker().track(frame), True)
            self._last_tracking_frame = index
        return FramePacket(index, self._video, mode, self._annotate(frame, rows, mode), rows, tracker_reset)

    def _annotate(self, frame: Any, rows: tuple[TeachingRow, ...], mode: str) -> Any:
        if mode == MODE_RAW:
            return frame.copy()
        cv2, image = self._get_cv2(), frame.copy()
        color = (0, 190, 255) if mode == MODE_DETECT else (0, 210, 0)
        for row in rows:
            x1, y1, x2, y2 = row.bbox
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            label = f"person {row.confidence:.2f}" if row.track_id is None else f"ID {row.track_id} {row.confidence:.2f}"
            cv2.putText(image, label, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
            if row.anchor is not None:
                cv2.circle(image, row.anchor, 4, color, -1)
        return image

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = self._video = self._detector = None
        self.reset_tracker()


class VisionTeachingWorker:
    """One daemon worker. Tk receives WorkerResult through after(), never directly."""

    def __init__(self, service: VisionTeachingService) -> None:
        self.service = service
        self._commands: Queue[tuple[int, str, tuple[Any, ...]] | None] = Queue()
        self.results: Queue[WorkerResult] = Queue()
        self._thread = Thread(target=self._run, name="huian-vision-teaching", daemon=True)
        self._thread.start()

    def submit(self, token: int, operation: str, *args: Any) -> None:
        self._commands.put((token, operation, args))

    def _run(self) -> None:
        while True:
            command = self._commands.get()
            if command is None:
                self.service.close()
                return
            token, operation, args = command
            try:
                self.results.put(WorkerResult(token, operation, getattr(self.service, operation)(*args)))
            except Exception as error:
                self.results.put(WorkerResult(token, operation, error=str(error)))

    def close(self) -> None:
        self._commands.put(None)
        self._thread.join(timeout=1.0)
