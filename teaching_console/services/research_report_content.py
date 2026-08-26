"""Evidence adapters, research narration, and screenshot capture for reports."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ReportScreenshot:
    path: Path
    caption: str


def display(value: object, fallback: str = "尚未填写") -> str:
    text = "" if value is None else str(value).strip()
    return text or fallback


def number(value: object, places: int = 2) -> str:
    return "—" if value is None else f"{float(value):.{places}f}"


def report_time(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f} 秒"
    except (TypeError, ValueError):
        return str(value).replace("T", " ")


def percent(value: object) -> str:
    return "暂无数据" if value is None else f"{float(value) * 100:.1f}%"


def student_response(value: object, prompt: str) -> str:
    text = "" if value is None else str(value).strip()
    return text or f"提示：{prompt}（可在教学台“填写研究计划与总结”中补充。）"


def research_method() -> tuple[str, ...]:
    return (
        "选择楼道人流原始视频作为测试对象。",
        "学生在不同时间点观察原始画面，独立记录真实人数。",
        "系统读取已保存的 AI 检测人数，和人工记录进行比较。",
        "根据误差和关键样本，分析 AI 的表现并提出改进方向。",
    )


def research_process_summary(
    experiment: Mapping[str, object],
    counts: Sequence[Mapping[str, object]],
    predictions: Sequence[Mapping[str, object]],
) -> str:
    video_name = Path(str(experiment.get("video_path") or "")).name or "测试视频"
    task_count = len(counts)
    parts = [
        f"本次实验选择《{video_name}》作为测试对象。学生先观察楼道人流画面，"
        f"在 {task_count} 个时间点独立记录真实人数，再与系统已经保存的 AI 检测结果进行比较。"
    ]
    if predictions:
        parts.append("实验还进行了未来人数预测验证：学生在预测目标时刻观察原始画面，记录真实人数，并比较 +10 秒、+20 秒、+30 秒的预测结果。")
    parts.append("最后，学生结合误差样本思考 AI 容易出错的原因，并提出下一步改进计划。")
    return "".join(parts)


def prediction_rows(store, experiment_id: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for annotation in store.prediction_annotations(experiment_id):
        for horizon in (10, 20, 30):
            prediction = annotation[f"prediction_{horizon}"]
            ground_truth = annotation[f"gt_{horizon}"]
            error = annotation[f"error_{horizon}"]
            if prediction is None and ground_truth is None and error is None:
                continue
            rows.append({
                "anchor_time_seconds": annotation["anchor_time_seconds"],
                "horizon_seconds": horizon,
                "target_time_seconds": float(annotation["anchor_time_seconds"]) + horizon,
                "prediction_count": prediction,
                "ground_truth_count": ground_truth,
                "absolute_error": error,
            })
    return rows


def existing_screenshots(directory: Path) -> list[ReportScreenshot]:
    results: list[ReportScreenshot] = []
    for path in sorted(directory.iterdir() if directory.exists() else ()):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp"}:
            continue
        try:
            from PIL import Image
            with Image.open(path) as image:
                image.verify()
        except (ImportError, OSError):
            continue
        results.append(ReportScreenshot(path, path.stem.replace("_", " ")))
    return results


def prepare_screenshots(
    experiment: Mapping[str, object],
    count_rows: Sequence[Mapping[str, object]],
    predictions: Sequence[Mapping[str, object]],
    directory: Path,
) -> list[ReportScreenshot]:
    """Preserve manual screenshots and add named evidence frames without inference."""
    directory.mkdir(parents=True, exist_ok=True)
    existing = existing_screenshots(directory)
    automatic = [item for item in existing if item.path.name[:4] in {"001_", "002_", "003_"}]
    manual = [item for item in existing if item not in automatic]
    needed = {
        "001_最大误差.png": "人数标注中 AI 与人工差异最大的样本。",
        "002_AI漏检.png": "AI 识别人数少于人工人数的漏检样本。",
        "003_预测误差最大.png": "未来人数预测误差最大的目标时刻。",
    }
    present = {item.path.name for item in automatic}
    if set(needed).issubset(present):
        return automatic + manual[:3]
    try:
        import cv2
    except ImportError:
        return automatic + manual[:3]
    video_path = Path(str(experiment.get("video_path") or ""))
    if not video_path.is_file():
        return automatic + manual[:3]

    count_errors = [row for row in count_rows if row.get("absolute_error") is not None]
    missed = [
        row for row in count_rows
        if row.get("system_count") is not None and row.get("ground_truth_count") is not None
        and float(row["system_count"]) < float(row["ground_truth_count"])
    ]
    prediction_errors = [row for row in predictions if row.get("absolute_error") is not None]
    candidates: list[tuple[str, str, float, int | None]] = []
    if count_errors and "001_最大误差.png" not in present:
        row = max(count_errors, key=lambda item: float(item["absolute_error"]))
        candidates.append(("001_最大误差.png", needed["001_最大误差.png"], float(row.get("video_time_seconds") or 0.0), int(row.get("frame_index") or 0)))
    if missed and "002_AI漏检.png" not in present:
        row = max(missed, key=lambda item: float(item["ground_truth_count"]) - float(item["system_count"]))
        candidates.append(("002_AI漏检.png", needed["002_AI漏检.png"], float(row.get("video_time_seconds") or 0.0), int(row.get("frame_index") or 0)))
    if prediction_errors and "003_预测误差最大.png" not in present:
        row = max(prediction_errors, key=lambda item: float(item["absolute_error"]))
        candidates.append(("003_预测误差最大.png", needed["003_预测误差最大.png"], float(row.get("target_time_seconds") or 0.0), None))
    if not candidates:
        return automatic + manual[:3]

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        capture.release()
        return automatic + manual[:3]
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    try:
        for filename, caption, seconds, frame_index in candidates:
            frame = int(round(seconds * fps)) if frame_index is None and fps > 0 else int(frame_index or 0)
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame)
            ok, image = capture.read()
            if not ok or image is None:
                continue
            output = directory / filename
            encoded_ok, encoded = cv2.imencode(".png", image)
            if not encoded_ok:
                continue
            encoded.tofile(str(output))
            automatic.append(ReportScreenshot(output, caption))
    finally:
        capture.release()
    return sorted(automatic, key=lambda item: item.path.name) + manual[:3]
