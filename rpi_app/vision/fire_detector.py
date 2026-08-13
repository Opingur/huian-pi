"""Independent visual Fire-only YOLO evidence component with optional tiled inference."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping
import math
import warnings

from ultralytics import YOLO


FIRE_CLASSES = frozenset({"fire"})


def tile_regions(frame_width: int, frame_height: int, rows: int, cols: int, overlap: float) -> list[tuple[int, int, int, int]]:
    """Return overlapping 2D tile rectangles as (x1, y1, x2, y2) in source-frame pixels."""
    if frame_width <= 0 or frame_height <= 0 or rows <= 0 or cols <= 0 or not 0.0 <= overlap < 1.0:
        raise ValueError("tile dimensions must be positive and tile_overlap must be in [0, 1)")
    core_width = math.ceil(frame_width / cols)
    core_height = math.ceil(frame_height / rows)
    margin_x = round(core_width * overlap / 2.0)
    margin_y = round(core_height * overlap / 2.0)
    regions: list[tuple[int, int, int, int]] = []
    for row in range(rows):
        for col in range(cols):
            core_x1 = col * core_width
            core_y1 = row * core_height
            core_x2 = min(frame_width, core_x1 + core_width)
            core_y2 = min(frame_height, core_y1 + core_height)
            regions.append((
                max(0, core_x1 - margin_x), max(0, core_y1 - margin_y),
                min(frame_width, core_x2 + margin_x), min(frame_height, core_y2 + margin_y),
            ))
    return regions


def map_tile_bbox_to_frame(
    bbox: list[float] | tuple[float, float, float, float], offset_x: int, offset_y: int,
    frame_width: int, frame_height: int,
) -> list[int] | None:
    """Map one real tile-local bbox to clipped source-frame coordinates."""
    x1 = max(0, min(frame_width, int(round(bbox[0] + offset_x))))
    y1 = max(0, min(frame_height, int(round(bbox[1] + offset_y))))
    x2 = max(0, min(frame_width, int(round(bbox[2] + offset_x))))
    y2 = max(0, min(frame_height, int(round(bbox[3] + offset_y))))
    return [x1, y1, x2, y2] if x2 > x1 and y2 > y1 else None


def bbox_iou(first: list[int], second: list[int]) -> float:
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    if intersection <= 0:
        return 0.0
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / float(first_area + second_area - intersection)


def merge_fire_detections(detections: list[dict[str, object]], iou_threshold: float = 0.5) -> list[dict[str, object]]:
    """Class-aware NMS preserving the highest-confidence real detection."""
    retained: list[dict[str, object]] = []
    for detection in sorted(detections, key=lambda item: float(item["confidence"]), reverse=True):
        if any(
            detection["class_name"] == existing["class_name"]
            and bbox_iou(list(detection["bbox"]), list(existing["bbox"])) >= iou_threshold
            for existing in retained
        ):
            continue
        retained.append(detection)
    return retained


class FireDetector:
    """Run the existing Fire model on a full BGR frame and optional overlapping tiles."""

    def __init__(self, config: Mapping[str, object] | None = None) -> None:
        self.config = dict(config or {})
        self.enabled = bool(self.config.get("enabled", False))
        self.confidence = float(self.config.get("confidence", 0.35))
        self.imgsz = int(self.config.get("imgsz", 640))
        self.tiled_inference = bool(self.config.get("tiled_inference", False))
        self.tile_rows = int(self.config.get("tile_rows", 2))
        self.tile_cols = int(self.config.get("tile_cols", 2))
        self.tile_overlap = float(self.config.get("tile_overlap", 0.15))
        self.full_frame_pass = bool(self.config.get("full_frame_pass", True))
        self.nms_iou_threshold = float(self.config.get("nms_iou_threshold", 0.5))
        if self.imgsz <= 0 or self.tile_rows <= 0 or self.tile_cols <= 0 or not 0.0 <= self.tile_overlap < 1.0:
            raise ValueError("fire_detection imgsz/tile dimensions must be positive and tile_overlap must be in [0, 1)")
        if not 0.0 < self.nms_iou_threshold <= 1.0:
            raise ValueError("fire_detection nms_iou_threshold must be in (0, 1]")
        self.model = None
        self.names: object = {}
        if not self.enabled:
            return
        model_path = Path(str(self.config.get("model_path", "../models/fire_n.pt")))
        if not model_path.is_absolute():
            model_path = Path(__file__).resolve().parents[1] / model_path
        if not model_path.is_file():
            raise FileNotFoundError(f"Fire model not found: {model_path}")
        self.model = YOLO(str(model_path))
        self.names = self.model.names
        labels = self._all_labels()
        unknown = sorted(label for label in labels if self._normalise_label(label) not in FIRE_CLASSES)
        if unknown:
            warnings.warn(f"Fire model has non-fire class names: {unknown}; visual Smoke is intentionally ignored.", RuntimeWarning)
        if not {self._normalise_label(label) for label in labels} & FIRE_CLASSES:
            warnings.warn("Fire model names contain no fire class; no visual fire evidence will be emitted.", RuntimeWarning)
        print(f"Fire model loaded: {model_path}; names={self.names}", flush=True)

    @staticmethod
    def _normalise_label(label: object) -> str:
        return str(label).strip().casefold()

    def _all_labels(self) -> list[str]:
        if isinstance(self.names, Mapping):
            return [str(label) for label in self.names.values()]
        return [str(label) for label in self.names] if isinstance(self.names, (list, tuple)) else []

    def _class_name(self, class_id: int) -> str | None:
        if isinstance(self.names, Mapping):
            value = self.names.get(class_id, self.names.get(str(class_id)))
        elif isinstance(self.names, (list, tuple)) and 0 <= class_id < len(self.names):
            value = self.names[class_id]
        else:
            value = None
        normalised = self._normalise_label(value) if value is not None else ""
        return normalised if normalised in FIRE_CLASSES else None

    def _extract_detections(self, result: Any, *, offset_x: int, offset_y: int,
                            frame_width: int, frame_height: int, source: str) -> list[dict[str, object]]:
        detections: list[dict[str, object]] = []
        boxes = result.boxes if result.boxes is not None else []
        for box in boxes:
            class_name = self._class_name(int(box.cls[0]))
            if class_name is None:
                continue
            mapped_bbox = map_tile_bbox_to_frame(box.xyxy[0].tolist(), offset_x, offset_y, frame_width, frame_height)
            if mapped_bbox is None:
                continue
            detections.append({
                "class_name": class_name,
                "confidence": round(float(box.conf[0]), 3),
                "bbox": mapped_bbox,
                "source": source,
            })
        return detections

    def detect(self, frame_bgr: Any) -> dict[str, object]:
        """Return model-derived raw detections, optionally combining full-frame and tiled passes."""
        if not self.enabled or self.model is None:
            return {
                "fire_detected": False, "smoke_detected": False,
                "fire_confidence": 0.0, "smoke_confidence": 0.0,
                "detections": [], "inference_ms": None, "inference_sources": [],
            }
        frame_height, frame_width = frame_bgr.shape[:2]
        passes: list[tuple[str, Any, int, int]] = []
        if not self.tiled_inference or self.full_frame_pass:
            passes.append(("full", frame_bgr, 0, 0))
        if self.tiled_inference:
            for x1, y1, x2, y2 in tile_regions(frame_width, frame_height, self.tile_rows, self.tile_cols, self.tile_overlap):
                passes.append(("tile", frame_bgr[y1:y2, x1:x2], x1, y1))
        started = perf_counter()
        raw_detections: list[dict[str, object]] = []
        sources: list[str] = []
        for source, image, offset_x, offset_y in passes:
            result = self.model(image, conf=self.confidence, imgsz=self.imgsz, verbose=False)[0]
            raw_detections.extend(self._extract_detections(
                result, offset_x=offset_x, offset_y=offset_y,
                frame_width=frame_width, frame_height=frame_height, source=source,
            ))
            if source not in sources:
                sources.append(source)
        detections = merge_fire_detections(raw_detections, self.nms_iou_threshold)
        fire_confidence = max((float(item["confidence"]) for item in detections if item["class_name"] == "fire"), default=0.0)
        return {
            "fire_detected": fire_confidence > 0.0,
            # Protocol compatibility only: visual Smoke is retired; ESP32 MQ-2 owns smoke detection.
            "smoke_detected": False,
            "fire_confidence": round(fire_confidence, 3),
            "smoke_confidence": 0.0,
            "detections": detections,
            "inference_ms": round((perf_counter() - started) * 1000.0, 2),
            "inference_sources": sources,
        }


class FireEvidenceTracker:
    """Fire-only confirmation, real-bbox hold, and visual-alert hold.

    Smoke-shaped fields remain false/zero for UART protocol compatibility; MQ-2 is
    the formal smoke source.
    """

    def __init__(self, config: Mapping[str, object] | None, enabled: bool) -> None:
        values = dict(config or {})
        self.enabled = bool(enabled)
        self.interval_seconds = float(values.get("interval_seconds", 1.0))
        self.confirmation_hits = int(values.get("confirmation_hits", 2))
        self.confirmation_window = int(values.get("confirmation_window", 4))
        legacy_hold = float(values.get("release_hold_seconds", 2.0))
        self.bbox_hold_seconds = float(values.get("bbox_hold_seconds", legacy_hold))
        self.visual_alert_hold_seconds = float(values.get("visual_alert_hold_seconds", legacy_hold))
        if (self.interval_seconds <= 0 or self.confirmation_hits <= 0
                or self.confirmation_window <= 0 or self.confirmation_hits > self.confirmation_window
                or self.bbox_hold_seconds < 0 or self.visual_alert_hold_seconds < 0):
            raise ValueError("fire_detection confirmation and hold settings are invalid")
        self.fire_history: deque[bool] = deque(maxlen=self.confirmation_window)
        self.stable_fire = False
        self.last_fire_detection_time: float | None = None
        self.last_fire_detections: list[dict[str, object]] = []
        self.last_fire_confidence = 0.0
        self.last_inference_time: float | None = None
        self.last_result = self._empty_result()
        self.inference_samples: deque[float] = deque(maxlen=30)

    @staticmethod
    def _empty_result() -> dict[str, object]:
        return {
            "fire_detected": False, "smoke_detected": False,
            "fire_confidence": 0.0, "smoke_confidence": 0.0,
            "detections": [], "inference_ms": None, "inference_sources": [],
        }

    def should_infer(self, source_timestamp: float) -> bool:
        return self.enabled and (self.last_inference_time is None or source_timestamp - self.last_inference_time >= self.interval_seconds)

    @staticmethod
    def _within(timestamp: float | None, now: float, seconds: float) -> bool:
        return timestamp is not None and now - timestamp <= seconds

    def _refresh_release_state(self, source_timestamp: float) -> None:
        if not self._within(self.last_fire_detection_time, source_timestamp, self.bbox_hold_seconds):
            self.last_fire_detections = []
        if self.stable_fire and not self._within(self.last_fire_detection_time, source_timestamp, self.visual_alert_hold_seconds):
            self.stable_fire = False
            self.last_fire_confidence = 0.0
            self.fire_history.clear()

    def record(self, result: Mapping[str, object], source_timestamp: float) -> None:
        self._refresh_release_state(source_timestamp)
        # Defence in depth: ignore a smoke key or smoke box from any future caller.
        fire_detections = [deepcopy(item) for item in result.get("detections", []) if item.get("class_name") == "fire"]
        raw_fire = bool(result.get("fire_detected", False)) and bool(fire_detections)
        fire_confidence = float(result.get("fire_confidence", 0.0)) if raw_fire else 0.0
        self.last_result = {
            **dict(result),
            "fire_detected": raw_fire,
            "smoke_detected": False,
            "fire_confidence": fire_confidence,
            "smoke_confidence": 0.0,
            "detections": fire_detections,
        }
        self.last_inference_time = source_timestamp
        self.fire_history.append(raw_fire)
        if raw_fire:
            self.last_fire_detection_time = source_timestamp
            self.last_fire_detections = fire_detections
            self.last_fire_confidence = fire_confidence
            if sum(self.fire_history) >= self.confirmation_hits:
                self.stable_fire = True
        if self.last_result.get("inference_ms") is not None:
            self.inference_samples.append(float(self.last_result["inference_ms"]))

    @staticmethod
    def _held_detections(detections: list[dict[str, object]]) -> list[dict[str, object]]:
        return [{**deepcopy(item), "temporal_hold": True} for item in detections]

    def status(self, source_timestamp: float) -> dict[str, object]:
        self._refresh_release_state(source_timestamp)
        result = self.last_result
        raw_fire = bool(result["fire_detected"])
        fire_recent = self.enabled and self._within(self.last_fire_detection_time, source_timestamp, self.visual_alert_hold_seconds)
        display_detections = list(result.get("detections", []))
        held_fire = not raw_fire and bool(self.last_fire_detections) and self._within(self.last_fire_detection_time, source_timestamp, self.bbox_hold_seconds)
        if held_fire:
            display_detections.extend(self._held_detections(self.last_fire_detections))
        age = None if self.last_inference_time is None else round(max(0.0, source_timestamp - self.last_inference_time), 2)
        return {
            "fire_detected_raw": raw_fire,
            "smoke_detected_raw": False,
            "recent_fire_evidence": bool(fire_recent),
            "recent_smoke_evidence": False,
            "vision_fire_suspected": bool(self.enabled and self.stable_fire),
            "vision_smoke_suspected": False,
            "vision_fire_confidence": float(result["fire_confidence"] if raw_fire else self.last_fire_confidence if fire_recent else 0.0),
            "vision_smoke_confidence": 0.0,
            "fire_model_enabled": self.enabled,
            "fire_model_last_inference_ms": result.get("inference_ms"),
            "fire_model_avg_inference_ms": None if not self.inference_samples else round(sum(self.inference_samples) / len(self.inference_samples), 2),
            "fire_detection_age": age,
            "fire_display_detections": display_detections,
            "fire_bbox_temporal_hold": held_fire,
            "fire_alert_temporal_hold": bool(fire_recent and not raw_fire),
            "fire_confirmed": False,
        }
def single_image_fire_status(result: Mapping[str, object], enabled: bool) -> dict[str, object]:
    """Image mode reports raw visual evidence only; it never claims temporal confirmation."""
    return {
        "fire_detected_raw": bool(result["fire_detected"]),
        "smoke_detected_raw": False,
        "vision_fire_suspected": False,
        "vision_smoke_suspected": False,
        "recent_fire_evidence": bool(result["fire_detected"]),
        "recent_smoke_evidence": False,
        "vision_fire_confidence": float(result["fire_confidence"]),
        "vision_smoke_confidence": 0.0,
        "fire_model_enabled": bool(enabled),
        "fire_model_last_inference_ms": result.get("inference_ms"),
        "fire_model_avg_inference_ms": result.get("inference_ms"),
        "fire_detection_age": 0.0 if enabled else None,
        "fire_display_detections": list(result.get("detections", [])),
        "fire_bbox_temporal_hold": False,
        "fire_alert_temporal_hold": False,
        "fire_confirmed": False,
    }