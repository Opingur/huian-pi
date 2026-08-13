"""YOLO person 检测封装；不承担区域、风险或通信职责。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ultralytics import YOLO


class PersonDetector:
    """只检测 COCO class 0（person），并返回统一检测框结构。"""

    def __init__(self, model_path: str | Path, confidence: float = 0.35) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"找不到 YOLO 模型：{path}。请确认 models/yolov8n.pt 已存在；"
                "本程序不会自动下载模型。"
            )
        self.model = YOLO(str(path))
        self.confidence = float(confidence)

    def detect(self, frame: Any) -> list[dict[str, float | int | str]]:
        """推理单帧并仅输出 person 检测框。"""
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
