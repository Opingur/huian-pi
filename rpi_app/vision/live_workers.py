"""Latest-frame background workers used only by the live camera path."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import Condition, Thread
from time import monotonic, perf_counter
from typing import Any, Callable

from vision.fire_detector import FireDetector, FireEvidenceTracker


@dataclass(frozen=True)
class WorkerSnapshot:
    version: int
    result: object | None
    source_timestamp: float | None
    inference_ms: float | None
    busy: bool
    error: str | None


class LatestFrameWorker:
    """One pending frame only: submissions overwrite stale work instead of building a queue."""

    def __init__(self, name: str, process: Callable[[Any, float], object], interval_seconds: float) -> None:
        if interval_seconds <= 0:
            raise ValueError("worker interval_seconds must be positive")
        self.name = name
        self._process = process
        self._interval_seconds = float(interval_seconds)
        self._condition = Condition()
        self._pending: tuple[Any, float] | None = None
        self._stop_requested = False
        self._busy = False
        self._version = 0
        self._result: object | None = None
        self._source_timestamp: float | None = None
        self._inference_ms: float | None = None
        self._error: str | None = None
        self._thread = Thread(target=self._run, name=f"huian-{name}-worker", daemon=True)
        self._thread.start()

    def submit(self, frame_bgr: Any, source_timestamp: float) -> None:
        """Copy exactly the latest frame so camera buffers cannot be reused by the worker."""
        with self._condition:
            self._pending = (frame_bgr.copy(), float(source_timestamp))
            self._condition.notify()

    def snapshot(self) -> WorkerSnapshot:
        with self._condition:
            return WorkerSnapshot(
                version=self._version,
                result=deepcopy(self._result),
                source_timestamp=self._source_timestamp,
                inference_ms=self._inference_ms,
                busy=self._busy,
                error=self._error,
            )

    def close(self, timeout_seconds: float = 5.0) -> None:
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()
        self._thread.join(timeout=timeout_seconds)
        if self._thread.is_alive():
            raise RuntimeError(f"{self.name} worker did not stop within {timeout_seconds:.1f}s")

    def _run(self) -> None:
        next_allowed = 0.0
        while True:
            with self._condition:
                while not self._stop_requested and self._pending is None:
                    self._condition.wait()
                if self._stop_requested:
                    return
                remaining = next_allowed - monotonic()
                if remaining > 0:
                    self._condition.wait(timeout=remaining)
                    continue
                frame_bgr, source_timestamp = self._pending
                self._pending = None
                self._busy = True
            started = perf_counter()
            try:
                result = self._process(frame_bgr, source_timestamp)
            except Exception as error:  # keep the worker alive and expose the failure to the live loop
                with self._condition:
                    self._error = f"{type(error).__name__}: {error}"
                    self._busy = False
                    self._condition.notify_all()
                print(f"{self.name} worker error: {error}", flush=True)
            else:
                with self._condition:
                    self._result = result
                    self._source_timestamp = source_timestamp
                    self._inference_ms = round((perf_counter() - started) * 1000.0, 2)
                    self._version += 1
                    self._error = None
                    self._busy = False
                    self._condition.notify_all()
            next_allowed = monotonic() + self._interval_seconds


class LatestFireWorker:
    """Fire worker sharing FireDetector/EvidenceTracker semantics with the offline pipeline."""

    def __init__(self, detector: FireDetector, evidence: FireEvidenceTracker, interval_seconds: float) -> None:
        self.detector = detector
        self.evidence = evidence
        self._evidence_condition = Condition()
        self._worker = None if not detector.enabled else LatestFrameWorker("fire", self._infer, interval_seconds)

    def _infer(self, frame_bgr: Any, source_timestamp: float) -> dict[str, object]:
        result = self.detector.detect(frame_bgr)
        with self._evidence_condition:
            self.evidence.record(result, source_timestamp)
            status = self.evidence.status(source_timestamp)
        sources = ",".join(result.get("inference_sources", [])) or "none"
        print(
            "Fire inference: "
            f"raw_fire={status['fire_detected_raw']} stable_fire={status['vision_fire_suspected']} "
            f"best_fire_confidence={status['vision_fire_confidence']:.3f} "
            f"detections={len(result.get('detections', []))} source={sources}",
            flush=True,
        )
        return status

    def submit(self, frame_bgr: Any, source_timestamp: float) -> None:
        if self._worker is not None:
            self._worker.submit(frame_bgr, source_timestamp)

    def status(self, source_timestamp: float) -> dict[str, object]:
        with self._evidence_condition:
            return self.evidence.status(source_timestamp)

    def snapshot(self) -> WorkerSnapshot:
        if self._worker is None:
            return WorkerSnapshot(0, None, None, None, False, None)
        return self._worker.snapshot()

    def close(self) -> None:
        if self._worker is not None:
            self._worker.close()