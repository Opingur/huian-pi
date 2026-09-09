"""Local showcase video analysis that forwards hardware status through the Pi.

Windows never opens an ESP32 serial port here.  When hardware forwarding is
configured, the formal visual pipeline publishes its compact status to the Pi
main process, which remains the sole UART owner.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable


class ShowcaseVisionError(RuntimeError):
    """A display-friendly error from the local presentation pipeline."""


class NoHardwarePublisher:
    """Publisher-shaped no-op used until the Pi bridge is explicitly configured."""

    enabled = False
    dry_run = True

    def send_status(self, _status: dict[str, object], *, source_timestamp: float | None = None) -> bool:
        return False

    def poll_esp32_status(self, *, now: float | None = None):
        return None

    def esp32_status_is_stale(self, *, now: float | None = None) -> bool:
        return True

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class ShowcaseFrame:
    frame_bgr: Any
    status: dict[str, object]
    source_time: float


@dataclass(frozen=True)
class ShowcaseEvent:
    kind: str
    value: object | None = None


SHOWCASE_VIDEO_WIDTH = 1280
SHOWCASE_VIDEO_HEIGHT = 740
HARDWARE_STATUS_HEARTBEAT_SECONDS = 1.0


def should_publish_showcase_status(
    status: dict[str, object],
    *,
    snapshot_saved: bool,
    previous_risk: str | None,
    last_publish_monotonic: float | None,
    now_monotonic: float,
) -> bool:
    """Return whether the Pi bridge must receive this display status now.

    Trend snapshots remain useful for normal telemetry, but alarm delivery must
    never wait for the next 15-second-history sample. A risk transition is
    therefore sent immediately, and every active warning is refreshed once a
    second so the Pi's short remote-control lease cannot expire mid-alarm.
    """
    risk = str(status.get("vision_risk", "NORMAL")).strip().upper() or "NORMAL"
    if risk != previous_risk:
        return True
    if snapshot_saved:
        return True
    return (
        risk != "NORMAL"
        and (last_publish_monotonic is None or now_monotonic - last_publish_monotonic >= HARDWARE_STATUS_HEARTBEAT_SECONDS)
    )


def is_low_resolution_showcase_frame(frame: Any) -> bool:
    """Return whether a source frame needs the clean low-resolution profile."""
    shape = getattr(frame, "shape", None)
    if not shape or len(shape) < 2:
        return False
    height, width = int(shape[0]), int(shape[1])
    return width < 960 or height < 540


def prepare_low_resolution_showcase_frame(cv2: Any, frame: Any) -> Any:
    """Resize/crop a small source *before* formal annotations are drawn.

    The Dashboard is 1280 x 740. Drawing labels on a 320 x 240 source and
    enlarging the completed image made every box, arrow, and caption four
    times too large. Native-resolution sources deliberately pass through
    unchanged.
    """
    if not is_low_resolution_showcase_frame(frame):
        return frame
    height, width = int(frame.shape[0]), int(frame.shape[1])
    scale = max(SHOWCASE_VIDEO_WIDTH / width, SHOWCASE_VIDEO_HEIGHT / height)
    resized_width = max(SHOWCASE_VIDEO_WIDTH, round(width * scale))
    resized_height = max(SHOWCASE_VIDEO_HEIGHT, round(height * scale))
    resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_CUBIC)
    left = max(0, (resized_width - SHOWCASE_VIDEO_WIDTH) // 2)
    top = max(0, (resized_height - SHOWCASE_VIDEO_HEIGHT) // 2)
    return resized[top:top + SHOWCASE_VIDEO_HEIGHT, left:left + SHOWCASE_VIDEO_WIDTH]


def apply_showcase_running_profile(config: dict[str, Any], profile: dict[str, float]) -> None:
    """Overlay the showcase-only running profile onto a copied formal config."""
    running_detection = dict(config.get("running_detection") or {})
    running_detection.update(profile)
    config["running_detection"] = running_detection

def apply_showcase_tracking_profile(config: dict[str, Any], root: Path) -> None:
    """Prefer detections and short-occlusion continuity for local showcase video.

    This profile is applied only to the copied Windows file-video config.  It
    keeps the verified 448-pixel model input, modestly recovers lower-confidence
    people, and gives ByteTrack extra time to reacquire a briefly blurred runner.
    """
    tracking = dict(config.get("tracking") or {})
    tracking["tracker"] = str(Path(root) / "rpi_app" / "configs" / "showcase_bytetrack.yaml")
    tracking["imgsz"] = 448
    config["tracking"] = tracking
    config["confidence"] = min(float(config.get("confidence", 0.35)), 0.30)

def apply_showcase_fire_profile(config: dict[str, Any]) -> None:
    """Restore the proven fire-analysis cadence for Windows showcase video.

    Person tracking is intentionally accelerated for the presentation runner.
    Fire analysis stays in its own latest-frame worker, so this copied config
    can restore tiled fire inference without slowing the Dashboard draw loop or
    changing the Raspberry Pi camera configuration.
    """
    fire_detection = dict(config.get("fire_detection") or {})
    # The worker retains only the newest frame. Its effective cadence is model
    # inference time plus this short back-pressure interval.
    fire_detection.update({
        "interval_seconds": 0.3,
        "tiled_inference": True,
    })
    config["fire_detection"] = fire_detection

def apply_low_resolution_presentation_profile(processor: Any) -> None:
    """Hide debugging overlays for small showcase footage without touching AI logic."""
    config = getattr(processor, "config", None)
    if not isinstance(config, dict):
        return
    display = dict(config.get("display") or {})
    display.update({
        "show_track_id": False,
        "show_trajectory": False,
        "show_direction_arrow": False,
    })
    config["display"] = display


def bridge_publisher(
    endpoint: str | None,
    bridge_key: str | None,
    *,
    factory: Callable[..., Any] | None = None,
) -> Any:
    """Create a network-only publisher, or a no-op if not configured.

    A missing key deliberately does *not* fall back to ESP32Publisher: that
    would risk Windows and the Pi competing for a physical serial device.
    """
    if not (endpoint or "").strip() or not (bridge_key or "").strip():
        return NoHardwarePublisher()
    if factory is None:
        rpi_dir = str(Path(__file__).resolve().parents[2] / "rpi_app")
        if rpi_dir not in sys.path:
            sys.path.insert(0, rpi_dir)
        from rpi_app.communication.pi_bridge import PiBridgePublisher
        factory = PiBridgePublisher
    return factory(str(endpoint).strip(), str(bridge_key).strip())


def _formal_components(root: Path, publisher: Any) -> tuple[Any, Any]:
    """Lazy-import the official pipeline only when a showcase actually starts."""
    rpi_dir = str((Path(root) / "rpi_app").resolve())
    if rpi_dir not in sys.path:
        sys.path.insert(0, rpi_dir)
    try:
        load_config = importlib.import_module("utils.config").load_config
        build_status = importlib.import_module("rpi_app.main").build_status
        processor_cls = importlib.import_module("vision.video_runner").TrackedFrameProcessor
        running_profile = importlib.import_module("vision.running_detector").SHOWCASE_RUNNING_DETECTION_PROFILE
    except (ImportError, AttributeError) as error:
        raise ShowcaseVisionError(f"无法载入正式视觉链：{error}") from error
    config_path = Path(root) / "rpi_app" / "configs" / "rpi_imx219_live.json"
    try:
        config = load_config(config_path)
    except OSError as error:
        raise ShowcaseVisionError(f"无法读取正式展示配置：{error}") from error
    # This is a Windows file-video demonstration, not a direct Pi camera run.
    config = dict(config)
    apply_showcase_running_profile(config, dict(running_profile))
    apply_showcase_tracking_profile(config, Path(root))
    apply_showcase_fire_profile(config)
    config["source_type"] = "video"
    config["display_window"] = False
    return processor_cls(config, build_status, publisher=publisher), config


class ShowcaseVisionWorker:
    """Background local-video runner; Tk only consumes its bounded event queue."""

    def __init__(
        self,
        root: Path,
        *,
        components_factory: Callable[[Path, Any], tuple[Any, Any]] = _formal_components,
        publisher_factory: Callable[..., Any] | None = None,
        cv2_loader: Callable[[], Any] | None = None,
    ) -> None:
        self.root = Path(root)
        self.events: queue.Queue[ShowcaseEvent] = queue.Queue(maxsize=3)
        self._components_factory = components_factory
        self._publisher_factory = publisher_factory
        self._cv2_loader = cv2_loader
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._seek_lock = threading.Lock()
        self._requested_seek_seconds: float | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def start(
        self, video_path: Path, *, bridge_endpoint: str = "", bridge_key: str = "",
        start_time_seconds: float = 0.0,
    ) -> None:
        self.stop()
        self._stop.clear()
        self._paused.clear()
        with self._seek_lock:
            self._requested_seek_seconds = None
        self._thread = threading.Thread(
            target=self._run,
            args=(Path(video_path), bridge_endpoint, bridge_key, max(0.0, float(start_time_seconds))),
            name="huian-showcase-vision",
            daemon=True,
        )
        self._thread.start()

    def pause(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()

    def seek(self, seconds: float) -> None:
        """Request one source-video seek; the worker applies it between frames."""
        with self._seek_lock:
            self._requested_seek_seconds = max(0.0, float(seconds))

    def _take_seek_request(self) -> float | None:
        with self._seek_lock:
            requested = self._requested_seek_seconds
            self._requested_seek_seconds = None
        return requested

    def stop(self) -> None:
        self._stop.set()
        self._paused.clear()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
        self._thread = None

    def _put(self, event: ShowcaseEvent) -> None:
        try:
            self.events.put_nowait(event)
        except queue.Full:
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
            self.events.put_nowait(event)

    def _run(self, video_path: Path, bridge_endpoint: str, bridge_key: str, start_time_seconds: float) -> None:
        processor = None
        capture = None
        try:
            if not video_path.is_file():
                raise ShowcaseVisionError(f"找不到展示视频：{video_path}")
            cv2 = self._cv2_loader() if self._cv2_loader else importlib.import_module("cv2")
            publisher = bridge_publisher(bridge_endpoint, bridge_key, factory=self._publisher_factory)
            processor, _config = self._components_factory(self.root, publisher)
            capture = cv2.VideoCapture(str(video_path))
            if not capture.isOpened():
                raise ShowcaseVisionError("无法打开展示视频。")
            fps = max(1.0, float(capture.get(cv2.CAP_PROP_FPS) or 0.0))
            frame_period = 1.0 / fps
            frame_count_property = getattr(cv2, "CAP_PROP_FRAME_COUNT", None)
            frame_count = int(capture.get(frame_count_property) or 0) if frame_count_property is not None else 0
            duration_seconds = frame_count / fps if frame_count > 0 else None
            frame_index = 0
            if start_time_seconds > 0:
                setter = getattr(capture, "set", None)
                if callable(setter):
                    setter(cv2.CAP_PROP_POS_MSEC, start_time_seconds * 1000.0)
                frame_index = int(round(start_time_seconds * fps))
            playback_started = time.monotonic() - frame_index * frame_period
            presentation_profile_applied = False
            last_published_risk: str | None = None
            last_publish_monotonic: float | None = None
            # The showcase must follow the source-video clock. The formal live
            # processor returns the newest completed AI result without making
            # the video renderer wait for a YOLO inference.
            process_frame = getattr(processor, "process_live_frame", processor.process_frame)
            self._put(ShowcaseEvent("started", {
                "video": video_path,
                "hardware": not isinstance(publisher, NoHardwarePublisher),
                "duration_seconds": duration_seconds,
            }))
            while not self._stop.is_set():
                requested_seek = self._take_seek_request()
                if requested_seek is not None:
                    # Seeking must not reuse ByteTrack IDs, trajectories, fire
                    # evidence, or prediction history from the previous moment.
                    processor.close()
                    publisher = bridge_publisher(bridge_endpoint, bridge_key, factory=self._publisher_factory)
                    processor, _config = self._components_factory(self.root, publisher)
                    process_frame = getattr(processor, "process_live_frame", processor.process_frame)
                    setter = getattr(capture, "set", None)
                    if callable(setter):
                        setter(cv2.CAP_PROP_POS_MSEC, requested_seek * 1000.0)
                    frame_index = int(round(requested_seek * fps))
                    playback_started = time.monotonic() - frame_index * frame_period
                    presentation_profile_applied = False
                    last_published_risk = None
                    last_publish_monotonic = None
                    self._put(ShowcaseEvent("seeked", requested_seek))
                if self._paused.is_set():
                    self._stop.wait(0.04)
                    playback_started += 0.04
                    continue

                # If rendering falls behind (for example because the UI is busy),
                # drop stale source frames rather than slowing the demonstration.
                due_frame_index = int((time.monotonic() - playback_started) / frame_period)
                frames_to_skip = max(0, due_frame_index - frame_index)
                for _ in range(frames_to_skip):
                    if not capture.grab():
                        break
                    frame_index += 1

                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                if not presentation_profile_applied:
                    if is_low_resolution_showcase_frame(frame):
                        apply_low_resolution_presentation_profile(processor)
                    presentation_profile_applied = True
                frame = prepare_low_resolution_showcase_frame(cv2, frame)
                source_time = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
                if source_time <= 0.0:
                    source_time = frame_index / fps
                annotated, status, snapshot_saved = process_frame(frame, source_time)
                now_monotonic = time.monotonic()
                if should_publish_showcase_status(
                    status,
                    snapshot_saved=snapshot_saved,
                    previous_risk=last_published_risk,
                    last_publish_monotonic=last_publish_monotonic,
                    now_monotonic=now_monotonic,
                ):
                    current_risk = str(status.get("vision_risk", "NORMAL")).strip().upper() or "NORMAL"
                    # A new alert must never wait behind the ordinary one-second
                    # telemetry throttle. If NORMAL was sent just before the
                    # Crowd Index crossed its threshold, send WARNING/CROWD now.
                    if current_risk != last_published_risk:
                        reset_interval = getattr(processor.publisher, "reset_send_interval", None)
                        if callable(reset_interval):
                            reset_interval()
                    delivered = processor.publisher.send_status(status, source_timestamp=now_monotonic)
                    # Do not mark a failed post as delivered: an active risk will
                    # then be retried instead of leaving the hardware silent.
                    if delivered:
                        last_published_risk = current_risk
                        last_publish_monotonic = now_monotonic
                self._put(ShowcaseEvent("frame", ShowcaseFrame(annotated, dict(status), source_time)))
                frame_index += 1
                remaining = playback_started + frame_index * frame_period - time.monotonic()
                if remaining > 0:
                    self._stop.wait(remaining)
            self._put(ShowcaseEvent("finished"))
        except Exception as error:
            self._put(ShowcaseEvent("error", str(error)))
        finally:
            if capture is not None:
                capture.release()
            if processor is not None:
                processor.close()
