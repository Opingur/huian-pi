"""Ultralytics ByteTrack person 追踪封装。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ultralytics import YOLO


class PersonTracker:
    """只追踪 COCO class 0（person），输出稳定的 ByteTrack ID。"""

    def __init__(self, model_path: str | Path, confidence: float, tracker: str = "bytetrack.yaml", imgsz: int = 640) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(f"找不到 YOLO 模型：{path}；程序不会自动下载模型。")
        self.model = YOLO(str(path))
        self.confidence = float(confidence)
        self.tracker = tracker
        self.imgsz = int(imgsz)

    def track(self, frame: Any) -> list[dict[str, float | int | str]]:
        """追踪一帧 person，返回检测框、Track ID 与底部中心锚点。"""
        result = self.model.track(
            frame,
            persist=True,
            tracker=self.tracker,
            classes=[0],
            conf=self.confidence,
            imgsz=self.imgsz,
            verbose=False,
        )[0]
        if result.boxes is None or result.boxes.id is None:
            return []

        tracked: list[dict[str, float | int | str]] = []
        for box in result.boxes:
            x1, y1, x2, y2 = (int(value) for value in box.xyxy[0].tolist())
            track_id = int(box.id[0])
            tracked.append(
                {
                    "class": "person",
                    "confidence": round(float(box.conf[0]), 3),
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "track_id": track_id,
                    "anchor_x": (x1 + x2) // 2,
                    "anchor_y": y2,
                }
            )
        return tracked
