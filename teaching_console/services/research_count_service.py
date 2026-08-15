"""Sampling, metrics and export for count-only research experiments."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from teaching_console.services.research_store import ResearchStore


def build_sample_tasks(duration: float, fps: float, target_sample_count: int = 25) -> list[tuple[float, int]]:
    """Uniform interior samples; never enumerate video frames."""
    if duration <= 0 or fps <= 0:
        raise ValueError("视频长度和 FPS 必须为正数。")
    count = max(1, min(30, target_sample_count))
    margin = min(0.5, duration * 0.05)
    usable = max(0.0, duration - 2 * margin)
    if count == 1:
        times = [duration / 2]
    else:
        times = [margin + usable * index / (count - 1) for index in range(count)]
    return [(round(time, 3), int(round(time * fps))) for time in times]


def safe_export_name(name: str | None, experiment_id: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', '_', name or '').strip()
    return cleaned or experiment_id


def export_directory(export_root: Path, experiment: dict) -> Path:
    root = Path(export_root); base = safe_export_name(experiment.get("name"), experiment["id"]); candidate = root / base
    def owns(path: Path) -> bool:
        try:
            return json.loads((path / "experiment_summary.json").read_text(encoding="utf-8"))["experiment"]["id"] == experiment["id"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            return False
    if not candidate.exists() or owns(candidate):
        return candidate
    candidate = root / f"{base}_{experiment['id'][:8]}"
    suffix = 2
    while candidate.exists() and not owns(candidate):
        candidate = root / f"{base}_{experiment['id'][:8]}_{suffix}"; suffix += 1
    return candidate


class ResearchCountService:
    def __init__(self, store: ResearchStore) -> None:
        self.store = store

    def generate_tasks(self, experiment_id: str, duration: float, fps: float, target_sample_count: int = 25) -> list:
        existing = self.store.annotations(experiment_id)
        if existing:
            return existing
        for sample_index, (time_seconds, frame_index) in enumerate(build_sample_tasks(duration, fps, target_sample_count), 1):
            self.store.create_count_annotation(experiment_id, sample_index, time_seconds, frame_index)
        return self.store.annotations(experiment_id)

    def add_key_sample(self, experiment_id: str, time_seconds: float, fps: float, system_count: int | None = None, note: str = "") -> str | None:
        for item in self.store.annotations(experiment_id):
            if abs(item["video_time_seconds"] - time_seconds) <= 0.1:
                return None
        items = self.store.annotations(experiment_id)
        annotation_id = self.store.create_count_annotation(
            experiment_id, len(items) + 1, time_seconds, int(round(time_seconds * fps)), system_count, note
        )
        return annotation_id

    def metrics(self, experiment_id: str) -> dict[str, int | float | None]:
        rows = self.store.annotations(experiment_id)
        completed = [row for row in rows if row["ground_truth_count"] is not None]
        evaluated = [row for row in completed if row["system_count"] is not None]
        if not evaluated:
            return {"total_tasks": len(rows), "completed_ground_truth": len(completed), "evaluated_samples": 0, "mae": None, "max_absolute_error": None, "exact_match_rate": None}
        errors = [float(row["absolute_error"]) for row in evaluated]
        return {"total_tasks": len(rows), "completed_ground_truth": len(completed), "evaluated_samples": len(evaluated), "mae": sum(errors) / len(errors), "max_absolute_error": max(errors), "exact_match_rate": sum(error == 0 for error in errors) / len(errors)}

    def export_experiment(self, experiment_id: str, export_root: Path) -> Path:
        experiment = self.store.get_experiment(experiment_id)
        if experiment is None:
            raise KeyError(experiment_id)
        rows, metrics = self.store.annotations(experiment_id), self.metrics(experiment_id)
        output = export_directory(Path(export_root), dict(experiment))
        output.mkdir(parents=True, exist_ok=True)
        with (output / "count_ground_truth.csv").open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["sample_index", "video_time_seconds", "frame_index", "system_count", "ground_truth_count", "absolute_error", "note"])
            writer.writerows((row["sample_index"], row["video_time_seconds"], row["frame_index"], row["system_count"], row["ground_truth_count"], row["absolute_error"], row["note"]) for row in rows)
        summary = {"experiment": dict(experiment), "progress": {"total_tasks": metrics["total_tasks"], "completed_ground_truth": metrics["completed_ground_truth"]}, "metrics": {key: metrics[key] for key in ("evaluated_samples", "mae", "max_absolute_error", "exact_match_rate")}, "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        (output / "experiment_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return output
