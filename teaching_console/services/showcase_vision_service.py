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
    except (ImportError, AttributeError) as error:
        raise ShowcaseVisionError(f"无法载入正式视觉链：{error}") from error
    config_path = Path(root) / "rpi_app" / "configs" / "rpi_imx219_live.json"
    try:
        config = load_config(config_path)
    except OSError as error:
        raise ShowcaseVisionError(f"无法读取正式展示配置：{error}") from error
    # This is a Windows file-video demonstration, not a direct Pi camera run.
    config = dict(config)
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
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def start(self, video_path: Path, *, bridge_endpoint: str = "", bridge_key: str = "") -> None:
        self.stop()
        self._stop.clear()
        self._paused.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(Path(video_path), bridge_endpoint, bridge_key),
            name="huian-showcase-vision",
            daemon=True,
        )
        self._thread.start()

    def pause(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()

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

    def _run(self, video_path: Path, bridge_endpoint: str, bridge_key: str) -> None:
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
            frame_index = 0
            self._put(ShowcaseEvent("started", {"video": video_path, "hardware": not isinstance(publisher, NoHardwarePublisher)}))
            while not self._stop.is_set():
                if self._paused.is_set():
                    self._stop.wait(0.04)
                    continue
                started = time.monotonic()
                ok, frame = capture.read()
                if not ok or frame is None:
                    break
                source_time = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
                if source_time <= 0.0:
                    source_time = frame_index / fps
                annotated, status, snapshot_saved = processor.process_frame(frame, source_time)
                if snapshot_saved:
                    processor.publisher.send_status(status, source_timestamp=source_time)
                self._put(ShowcaseEvent("frame", ShowcaseFrame(annotated, dict(status), source_time)))
                frame_index += 1
                remaining = (1.0 / fps) - (time.monotonic() - started)
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
