"""Pure, local services for the YOLO fine-tuning teaching workflow.

This module deliberately never imports Ultralytics or calls ``model.train``.
It prepares evidence, datasets and Colab packages; model execution belongs to
the explicit remote Colab workflow.
"""
from __future__ import annotations

import json
import math
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PERSON_CLASS_ID = 0
VALID_SPLITS = ("train", "val", "test")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mapping_value(item: Mapping[str, Any] | object, name: str, default: Any = None) -> Any:
    return item.get(name, default) if isinstance(item, Mapping) else getattr(item, name, default)


def _video_key(path: str | Path) -> str:
    """Stable, Windows-friendly identity for video-level split validation."""
    return str(path).replace("\\", "/").strip().casefold()


class DataLeakageError(ValueError):
    """A source video was assigned to more than one data split."""


@dataclass(frozen=True)
class HardFrameRecommendation:
    frame_index: int
    time_seconds: float
    system_count: int
    average_confidence: float | None
    minimum_confidence: float | None
    score: float
    reasons: tuple[str, ...]
    source: Mapping[str, Any]


class HardFrameSelector:
    """Deterministically rank difficult frames without running a detector."""

    MIN_LIMIT = 5
    MAX_LIMIT = 25

    @classmethod
    def select(
        cls,
        records: Iterable[Mapping[str, Any]],
        limit: int = 25,
        min_time_gap_seconds: float = 1.0,
    ) -> list[HardFrameRecommendation]:
        if not cls.MIN_LIMIT <= int(limit) <= cls.MAX_LIMIT:
            raise ValueError("困难帧数量必须在 5 到 25 之间。")
        if min_time_gap_seconds < 0:
            raise ValueError("时间去重间隔不能为负数。")
        ordered = sorted((dict(row) for row in records), key=lambda row: (float(row.get("time_seconds", 0)), int(row.get("frame_index", 0))))
        candidates = [cls._recommend(row, ordered, index) for index, row in enumerate(ordered)]
        candidates.sort(key=lambda item: (-item.score, item.time_seconds, item.frame_index))
        selected: list[HardFrameRecommendation] = []
        for candidate in candidates:
            if all(abs(candidate.time_seconds - prior.time_seconds) >= min_time_gap_seconds for prior in selected):
                selected.append(candidate)
                if len(selected) == int(limit):
                    break
        return selected

    @staticmethod
    def _recommend(row: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], index: int) -> HardFrameRecommendation:
        people = max(0, int(row.get("system_count", 0) or 0))
        raw_confidences = row.get("confidences") or ()
        confidences = [float(value) for value in raw_confidences if value is not None]
        average = sum(confidences) / len(confidences) if confidences else None
        minimum = min(confidences) if confidences else None
        low_count = sum(value < 0.5 for value in confidences)
        intersection = float(row.get("intersection_count", row.get("flow_conflicts", 0)) or 0)
        gt_count = row.get("ground_truth_count")
        gt_error = abs(people - int(gt_count)) if gt_count is not None else 0
        jump = 0
        if index:
            jump = abs(people - max(0, int(rows[index - 1].get("system_count", 0) or 0)))
        score = float(people) + low_count * 2.0 + intersection * 2.0 + jump * 1.5 + gt_error * 4.0
        if average is not None:
            score += max(0.0, 0.6 - average) * 5.0
        reasons: list[str] = []
        if people:
            reasons.append(f"人数较多（{people}）")
        if low_count:
            reasons.append(f"低置信度检测 {low_count} 个")
        if intersection:
            reasons.append("多人方向交汇")
        if jump:
            reasons.append(f"人数跳变 {jump}")
        if gt_count is not None and gt_error:
            reasons.append(f"与已有 GT 相差 {gt_error}")
        if not reasons:
            reasons.append("用于均匀覆盖视频")
        return HardFrameRecommendation(
            frame_index=int(row.get("frame_index", 0)), time_seconds=float(row.get("time_seconds", 0.0)),
            system_count=people, average_confidence=average, minimum_confidence=minimum,
            score=round(score, 6), reasons=tuple(reasons), source=row,
        )


@dataclass(frozen=True)
class BoundingBox:
    """An original-image xyxy person box, clamped only when dimensions are known."""

    x1: float
    y1: float
    x2: float
    y2: float

    def normalized(self) -> "BoundingBox":
        return BoundingBox(min(self.x1, self.x2), min(self.y1, self.y2), max(self.x1, self.x2), max(self.y1, self.y2))

    def clamp(self, width: float, height: float) -> "BoundingBox":
        box = self.normalized()
        return BoundingBox(max(0.0, min(width, box.x1)), max(0.0, min(height, box.y1)), max(0.0, min(width, box.x2)), max(0.0, min(height, box.y2)))

    def moved(self, dx: float, dy: float, width: float, height: float) -> "BoundingBox":
        box = self.clamp(width, height)
        dx = min(max(dx, -box.x1), width - box.x2)
        dy = min(max(dy, -box.y1), height - box.y2)
        return BoundingBox(box.x1 + dx, box.y1 + dy, box.x2 + dx, box.y2 + dy)

    def resized(self, edge: str, x: float, y: float, width: float, height: float, minimum_size: float = 1.0) -> "BoundingBox":
        """Resize a named edge/corner (``left``, ``top_right`` etc.) in image coordinates."""
        box = self.clamp(width, height)
        x, y = max(0.0, min(width, x)), max(0.0, min(height, y))
        x1 = x if "left" in edge else box.x1
        x2 = x if "right" in edge else box.x2
        y1 = y if "top" in edge else box.y1
        y2 = y if "bottom" in edge else box.y2
        if x2 - x1 < minimum_size:
            if "left" in edge:
                x1 = x2 - minimum_size
            else:
                x2 = x1 + minimum_size
        if y2 - y1 < minimum_size:
            if "top" in edge:
                y1 = y2 - minimum_size
            else:
                y2 = y1 + minimum_size
        return BoundingBox(x1, y1, x2, y2).clamp(width, height)


@dataclass(frozen=True)
class CanvasImageTransform:
    """Map a letterboxed canvas display to immutable original frame coordinates."""

    original_width: int
    original_height: int
    display_x: float
    display_y: float
    display_width: float
    display_height: float

    def canvas_to_image(self, x: float, y: float) -> tuple[float, float]:
        if self.display_width <= 0 or self.display_height <= 0:
            raise ValueError("显示图像尺寸必须为正数。")
        image_x = (x - self.display_x) * self.original_width / self.display_width
        image_y = (y - self.display_y) * self.original_height / self.display_height
        return max(0.0, min(float(self.original_width), image_x)), max(0.0, min(float(self.original_height), image_y))

    def image_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        x = max(0.0, min(float(self.original_width), x))
        y = max(0.0, min(float(self.original_height), y))
        return self.display_x + x * self.display_width / self.original_width, self.display_y + y * self.display_height / self.original_height

    def canvas_box_to_image(self, x1: float, y1: float, x2: float, y2: float) -> BoundingBox:
        first = self.canvas_to_image(x1, y1)
        second = self.canvas_to_image(x2, y2)
        return BoundingBox(*first, *second).normalized().clamp(self.original_width, self.original_height)


def coerce_box(value: BoundingBox | Mapping[str, Any] | Sequence[float]) -> BoundingBox:
    if isinstance(value, BoundingBox):
        return value.normalized()
    if isinstance(value, Mapping):
        return BoundingBox(float(value["x1"]), float(value["y1"]), float(value["x2"]), float(value["y2"])).normalized()
    if len(value) != 4:
        raise ValueError("Bounding box 必须有 x1, y1, x2, y2 四个坐标。")
    return BoundingBox(*(float(v) for v in value)).normalized()


def yolo_xywh(box: BoundingBox | Mapping[str, Any] | Sequence[float], image_width: int, image_height: int) -> tuple[float, float, float, float]:
    if image_width <= 0 or image_height <= 0:
        raise ValueError("图像尺寸必须为正数。")
    item = coerce_box(box).clamp(image_width, image_height)
    width, height = item.x2 - item.x1, item.y2 - item.y1
    if width <= 0 or height <= 0:
        raise ValueError("Bounding box 必须具有正面积。")
    return ((item.x1 + item.x2) / 2 / image_width, (item.y1 + item.y2) / 2 / image_height, width / image_width, height / image_height)


def yolo_label(box: BoundingBox | Mapping[str, Any] | Sequence[float], image_width: int, image_height: int, class_id: int = PERSON_CLASS_ID) -> str:
    if class_id != PERSON_CLASS_ID:
        raise ValueError("当前 Detection Ground Truth 只支持 person class id = 0。")
    return f"0 {' '.join(f'{value:.6f}' for value in yolo_xywh(box, image_width, image_height))}"


def validate_video_splits(assignments: Mapping[str | Path, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for source_video, split in assignments.items():
        if split not in VALID_SPLITS:
            raise ValueError(f"未知数据集划分：{split}")
        key = _video_key(source_video)
        prior = normalized.get(key)
        if prior is not None and prior != split:
            raise DataLeakageError(f"同一 source_video 不能同时属于 {prior} 和 {split}：{source_video}")
        normalized[key] = split
    return normalized


@dataclass(frozen=True)
class DatasetBuildResult:
    dataset_dir: Path
    frame_count: int
    annotation_count: int
    split_assignments: dict[str, str]


class DatasetBuilder:
    """Create an Ultralytics detection dataset from saved human boxes."""

    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root)

    def build(self, dataset_name: str, annotations: Iterable[Mapping[str, Any]], split_assignments: Mapping[str | Path, str]) -> DatasetBuildResult:
        safe_name = _safe_name(dataset_name)
        rows = [dict(row) for row in annotations]
        split_keys = validate_video_splits(split_assignments)
        source_display: dict[str, str] = {}
        for row in rows:
            source = row.get("source_video")
            if not source:
                raise ValueError("每个 Detection Ground Truth 必须包含 source_video。")
            key = _video_key(source)
            explicit = row.get("split")
            assigned = split_keys.get(key)
            if assigned is None:
                if explicit not in VALID_SPLITS:
                    raise ValueError(f"未为 source_video 分配 train/val/test：{source}")
                split_keys[key] = explicit
            elif explicit is not None and explicit != assigned:
                raise DataLeakageError(f"标注记录与视频级划分冲突：{source}")
            source_display[key] = str(source)
        target = self.data_root / "datasets" / safe_name
        for split in VALID_SPLITS:
            (target / "images" / split).mkdir(parents=True, exist_ok=True)
            (target / "labels" / split).mkdir(parents=True, exist_ok=True)
        seen: set[tuple[str, int]] = set()
        annotation_count = 0
        for row in rows:
            source = str(row["source_video"])
            split = split_keys[_video_key(source)]
            frame_path = Path(str(row["frame_path"]))
            if not frame_path.is_file():
                raise FileNotFoundError(f"找不到标注帧：{frame_path}")
            frame_index = int(row.get("frame_index", 0))
            unique_key = (_video_key(source), frame_index)
            if unique_key in seen:
                raise ValueError(f"同一视频帧重复进入数据集：{source} / {frame_index}")
            seen.add(unique_key)
            stem = f"{sha1(_video_key(source).encode('utf-8')).hexdigest()[:10]}_f{frame_index:06d}"
            image_target = target / "images" / split / f"{stem}{frame_path.suffix.lower() or '.jpg'}"
            label_target = target / "labels" / split / f"{stem}.txt"
            shutil.copy2(frame_path, image_target)
            width, height = int(row["image_width"]), int(row["image_height"])
            labels = [yolo_label(box, width, height) for box in row.get("boxes", ())]
            label_target.write_text("\n".join(labels) + ("\n" if labels else ""), encoding="utf-8")
            annotation_count += len(labels)
        data_yaml = _dataset_yaml()
        (target / "data.yaml").write_text(data_yaml, encoding="utf-8")
        metadata = {
            "dataset_name": safe_name, "created_at": _utc_now(), "base_model": "models/yolov8n.pt",
            "source_videos": [source_display[key] for key in sorted(source_display)],
            "split_assignment": {source_display[key]: split_keys[key] for key in sorted(source_display)},
            "frame_count": len(rows), "annotation_count": annotation_count,
        }
        (target / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return DatasetBuildResult(target, len(rows), annotation_count, {source_display[key]: split_keys[key] for key in sorted(source_display)})


def _dataset_yaml() -> str:
    return "path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: person\n"


def _safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in value.strip())
    if not cleaned:
        raise ValueError("名称不能为空。")
    return cleaned


@dataclass(frozen=True)
class TrainingPackageResult:
    package_dir: Path
    dataset_zip: Path
    notebook: Path
    train_script: Path


class ColabPackageBuilder:
    """Build an inspectable Colab hand-off; never starts a local training job."""

    def __init__(self, project_root: Path, *, template_root: Path | None = None) -> None:
        self.project_root = Path(project_root)
        self.template_root = Path(template_root) if template_root is not None else self.project_root

    def build(self, dataset_dir: Path, dataset_name: str, epochs: int = 50, imgsz: int = 640) -> TrainingPackageResult:
        dataset_dir = Path(dataset_dir)
        if not (dataset_dir / "data.yaml").is_file():
            raise FileNotFoundError("数据集缺少 data.yaml。")
        if epochs <= 0 or imgsz <= 0:
            raise ValueError("epochs 与 imgsz 必须为正数。")
        safe_name = _safe_name(dataset_name)
        output = self.project_root / "training_packages" / safe_name
        output.mkdir(parents=True, exist_ok=True)
        zip_path = output / "dataset.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(dataset_dir.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, Path("dataset") / file_path.relative_to(dataset_dir))
        train_source = self.template_root / "training" / "train.py"
        if not train_source.is_file():
            raise FileNotFoundError(f"缺少真实训练源码：{train_source}")
        train_script = output / "train.py"
        shutil.copy2(train_source, train_script)
        shutil.copy2(dataset_dir / "data.yaml", output / "data.yaml")
        experiment = {"dataset_name": safe_name, "base_model": "yolov8n.pt", "epochs": int(epochs), "imgsz": int(imgsz), "training_platform": "Google Colab GPU", "created_at": _utc_now()}
        (output / "experiment.json").write_text(json.dumps(experiment, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "README.md").write_text(_readme_text(experiment), encoding="utf-8")
        notebook = output / "train_colab.ipynb"
        notebook.write_text(json.dumps(_notebook(experiment), ensure_ascii=False, indent=2), encoding="utf-8")
        return TrainingPackageResult(output, zip_path, notebook, train_script)


def _readme_text(experiment: Mapping[str, Any]) -> str:
    return ("# 慧安 YOLO Fine-tune Colab 训练包\n\n"
            "本机不训练。请在 Google Colab 登录账号，选择 GPU Runtime，上传 `dataset.zip`、`train.py` 与本目录的 `train_colab.ipynb`，再按中文单元格顺序执行。\n\n"
            f"基础模型：`{experiment['base_model']}`；Epoch：{experiment['epochs']}；imgsz：{experiment['imgsz']}。\n")


def _notebook(experiment: Mapping[str, Any]) -> dict[str, Any]:
    cells = [
        ("markdown", "# 慧安 YOLOv8 人体检测微调\n按顺序执行：检查 GPU → 安装依赖 → 上传数据集 → 检查数据 → 训练 → 验证 → 下载 best.pt。"),
        ("code", "import torch\nassert torch.cuda.is_available(), '未检测到 CUDA GPU；请在 Colab 运行时设置中选择 GPU'\nprint('CUDA GPU:', torch.cuda.get_device_name(0))"),
        ("code", "!pip -q install ultralytics"),
        ("markdown", "## 3. 上传 dataset.zip 和 train.py\n在左侧文件栏同时上传本训练包中的 dataset.zip 与 train.py。"),
        ("code", "from google.colab import files\nuploaded = files.upload()\nassert 'dataset.zip' in uploaded and 'train.py' in uploaded, '请同时上传 dataset.zip 与 train.py'"),
        ("code", "!unzip -q /content/dataset.zip -d /content\n!cat /content/dataset/data.yaml"),        ("markdown", "## 5. 查看少量数据样例"),
        ("code", "from pathlib import Path\nimages = list(Path('/content/dataset/images/train').glob('*'))\nprint('train images:', len(images))\nprint(images[:3])"),
        ("markdown", "## 6. 开始训练（真实 Ultralytics YOLOv8 代码）"),
        ("code", f"!python /content/train.py --data /content/dataset/data.yaml --epochs {experiment['epochs']} --imgsz {experiment['imgsz']} --model yolov8n.pt --seed 42"),
        ("markdown", "## 7. 验证与指标\n训练命令会执行验证；查看输出中的 Precision、Recall、mAP。"),
        ("code", "!ls -lh /content/runs/huian_finetune/*/weights/best.pt"),
        ("markdown", "## 9. 导出 best.pt\n下载 best.pt 后，在教学台中使用“导入 best.pt”，不会覆盖基础 yolov8n.pt。"),
    ]
    return {"nbformat": 4, "nbformat_minor": 5, "metadata": {"kernelspec": {"display_name": "Python 3", "name": "python3"}}, "cells": [{"cell_type": kind, "metadata": {}, "source": [text + "\n"], "outputs": [], "execution_count": None} for kind, text in cells]}


@dataclass(frozen=True)
class ImportedCandidate:
    model_path: Path
    metadata_path: Path


class CandidateModelManager:
    """Import Colab output under models/experiments without ever touching baseline."""

    def __init__(self, project_root: Path, baseline_model_path: Path | None = None) -> None:
        self.project_root = Path(project_root)
        self.baseline_model_path = None if baseline_model_path is None else Path(baseline_model_path)
    def import_best_pt(self, dataset_name: str, source_best_pt: Path, *, training_date: str | None = None, epochs: int = 50, imgsz: int = 640) -> ImportedCandidate:
        source = Path(source_best_pt)
        if not source.is_file():
            raise FileNotFoundError(f"找不到 Colab 导出的 best.pt：{source}")
        baseline = (self.baseline_model_path or self.project_root / "models" / "yolov8n.pt").resolve()
        if source.resolve() == baseline:
            raise ValueError("不能把基础 yolov8n.pt 当作候选 best.pt 导入。")
        output = self.project_root / "models" / "experiments" / _safe_name(dataset_name)
        output.mkdir(parents=True, exist_ok=True)
        target = output / "best.pt"
        shutil.copy2(source, target)
        metadata_path = output / "result_metadata.json"
        metadata = {"dataset": _safe_name(dataset_name), "training_date": training_date, "base_model": "yolov8n.pt", "epochs": int(epochs), "imgsz": int(imgsz), "source_file": str(source), "imported_at": _utc_now()}
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return ImportedCandidate(target, metadata_path)


def box_iou(left: BoundingBox | Mapping[str, Any] | Sequence[float], right: BoundingBox | Mapping[str, Any] | Sequence[float]) -> float:
    a, b = coerce_box(left), coerce_box(right)
    intersect_w = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    intersect_h = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    intersection = intersect_w * intersect_h
    union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - intersection
    return intersection / union if union > 0 else 0.0


def _single_frame_metrics(ground_truth: Sequence[Any], predictions: Sequence[Any], iou_threshold: float) -> dict[str, int]:
    """Greedily match each prediction to one GT box at the declared IoU threshold."""
    unmatched = set(range(len(ground_truth)))
    true_positives = 0
    for detected in predictions:
        best = max(unmatched, key=lambda index: box_iou(detected, ground_truth[index]), default=None)
        if best is not None and box_iou(detected, ground_truth[best]) >= iou_threshold:
            unmatched.remove(best)
            true_positives += 1
    return {
        "ground_truth_count": len(ground_truth),
        "model_count": len(predictions),
        "absolute_count_error": abs(len(predictions) - len(ground_truth)),
        "true_positives": true_positives,
        "false_positives": len(predictions) - true_positives,
        "false_negatives": len(unmatched),
    }


def _detection_metrics(ground_truth: Mapping[str, Sequence[Any]], predictions: Mapping[str, Sequence[Any]], iou_threshold: float) -> dict[str, int | float | None]:
    rows = [_single_frame_metrics(boxes, list(predictions.get(frame_id, ())), iou_threshold) for frame_id, boxes in ground_truth.items()]
    true_positives = sum(row["true_positives"] for row in rows)
    false_positives = sum(row["false_positives"] for row in rows)
    false_negatives = sum(row["false_negatives"] for row in rows)
    errors = [row["absolute_count_error"] for row in rows]
    return {
        "frames": len(rows),
        "ground_truth_boxes": sum(row["ground_truth_count"] for row in rows),
        "model_detections": sum(row["model_count"] for row in rows),
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "precision": None if true_positives + false_positives == 0 else true_positives / (true_positives + false_positives),
        "recall": None if true_positives + false_negatives == 0 else true_positives / (true_positives + false_negatives),
        "count_mae": None if not errors else sum(errors) / len(errors),
        "max_count_error": None if not errors else max(errors),
        "exact_count_rate": None if not errors else sum(error == 0 for error in errors) / len(errors),
        "map50": None,
        "map50_95": None,
    }

class ABComparisonService:
    """Calculate A/B metrics from exactly the same, independently supplied GT boxes."""

    def compare(self, shared_ground_truth: Iterable[Mapping[str, Any]], baseline_predictions: Mapping[str, Sequence[Any]], candidate_predictions: Mapping[str, Sequence[Any]], iou_threshold: float = 0.5) -> dict[str, Any]:
        if not 0 < iou_threshold <= 1:
            raise ValueError("IoU 阈值必须在 (0, 1]。")
        ground_truth: dict[str, Sequence[Any]] = {}
        for row in shared_ground_truth:
            frame_id = str(row.get("frame_id", row.get("id", "")))
            if not frame_id:
                raise ValueError("A/B Ground Truth 必须包含 frame_id。")
            if frame_id in ground_truth:
                raise ValueError(f"重复 Ground Truth frame_id：{frame_id}")
            ground_truth[frame_id] = list(row.get("boxes", ()))
        extras = (set(baseline_predictions) | set(candidate_predictions)) - set(ground_truth)
        if extras:
            raise ValueError(f"预测结果包含非 test Ground Truth 帧：{sorted(extras)}")
        samples = []
        for frame_id, boxes in ground_truth.items():
            baseline = _single_frame_metrics(boxes, list(baseline_predictions.get(frame_id, ())), iou_threshold)
            candidate = _single_frame_metrics(boxes, list(candidate_predictions.get(frame_id, ())), iou_threshold)
            samples.append({"frame_id": frame_id, "ground_truth_count": len(boxes), "baseline": baseline, "candidate": candidate})
        return {
            "ground_truth_frame_ids": list(ground_truth),
            "iou_threshold": iou_threshold,
            "baseline": _detection_metrics(ground_truth, baseline_predictions, iou_threshold),
            "candidate": _detection_metrics(ground_truth, candidate_predictions, iou_threshold),
            "samples": samples,
        }