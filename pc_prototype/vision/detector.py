"""YOLO 人员检测封装。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ultralytics import YOLO


class PersonDetector:
    """只输出 person 类别的 YOLO 检测结果。"""

    def __init__(self, model_path: str, confidence: float = 0.4) -> None:
        self.model = YOLO(model_path)
        self.confidence = confidence

    def detect(self, frame: Any) -> list[dict[str, float | int | str]]:
        """检测单帧画面，并返回统一的人员检测数据。"""
        result = self.model(frame, classes=[0], conf=self.confidence, verbose=False)[0]
        detections: list[dict[str, float | int | str]] = []

        for box in result.boxes:
            x1, y1, x2, y2 = (int(value) for value in box.xyxy[0].tolist())
            detections.append(
                {
                    "class": "person",
                    "confidence": round(float(box.conf[0]), 3),
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                }
            )
        return detections


def resolve_model_path(configured_path: str) -> str:
    """兼容新目录结构和当前项目根目录中的既有模型文件。"""
    configured = Path(configured_path)
    if configured.exists():
        return str(configured)

    legacy_path = Path("yolov8n.pt")
    if legacy_path.exists():
        print("提示：使用项目根目录中的现有模型 yolov8n.pt。")
        return str(legacy_path)

    return str(configured)
