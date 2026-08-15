"""Fake-timeline research logic for frozen short-term prediction evidence."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from teaching_console.services.research_count_service import ResearchCountService
from teaching_console.services.research_store import ResearchStore


HORIZONS = (10, 20, 30)


class ResearchPredictionService:
    def __init__(self, store: ResearchStore) -> None:
        self.store = store

    @staticmethod
    def _valid(item: dict, duration: float) -> bool:
        return (
            item.get("prediction_slope") is not None
            and all(item.get(f"prediction_{horizon}") is not None for horizon in HORIZONS)
            and float(item["time_seconds"]) + 30 <= duration
        )

    def generate_anchors(self, experiment_id: str, timeline: list[dict], video_duration_seconds: float, target_anchor_count: int = 5) -> list:
        existing = self.store.prediction_annotations(experiment_id)
        if existing:
            return existing
        valid = [item for item in timeline if self._valid(item, video_duration_seconds)]
        count = min(max(0, target_anchor_count), 5, len(valid))
        if count == 1:
            selected = [valid[len(valid) // 2]]
        elif count:
            selected = [valid[round(index * (len(valid) - 1) / (count - 1))] for index in range(count)]
        else:
            selected = []
        for item in selected:
            self.store.create_prediction_annotation(
                experiment_id, item["time_seconds"], item["frame_index"], item["current_system_count"],
                item["prediction_slope"], item["prediction_10"], item["prediction_20"], item["prediction_30"],
            )
        return self.store.prediction_annotations(experiment_id)

    def save_prediction_gt(self, annotation_id: str, horizon_seconds: int, ground_truth_count: int) -> None:
        if horizon_seconds not in HORIZONS:
            raise ValueError("预测验证只支持 +10、+20、+30 秒。")
        if isinstance(ground_truth_count, bool) or not isinstance(ground_truth_count, int) or ground_truth_count < 0:
            raise ValueError("人工真实人数必须是非负整数。")
        self.store.update_prediction_ground_truth(annotation_id, horizon_seconds, ground_truth_count)

    def find_existing_count_ground_truth(self, experiment_id: str, target_time_seconds: float, tolerance_seconds: float = 0.1) -> int | None:
        matches = [row for row in self.store.annotations(experiment_id) if row["ground_truth_count"] is not None and abs(row["video_time_seconds"] - target_time_seconds) <= tolerance_seconds]
        if not matches:
            return None
        return int(min(matches, key=lambda row: abs(row["video_time_seconds"] - target_time_seconds))["ground_truth_count"])

    def apply_existing_count_gt(self, prediction_annotation_id: str, horizon_seconds: int) -> int | None:
        with self.store._connection() as connection:
            connection.row_factory = __import__("sqlite3").Row
            prediction = connection.execute("SELECT experiment_id, anchor_time_seconds FROM prediction_annotations WHERE id = ?", (prediction_annotation_id,)).fetchone()
        if prediction is None:
            raise KeyError(prediction_annotation_id)
        count = self.find_existing_count_ground_truth(prediction["experiment_id"], prediction["anchor_time_seconds"] + horizon_seconds)
        if count is not None:
            self.save_prediction_gt(prediction_annotation_id, horizon_seconds, count)
        return count

    def prediction_metrics(self, experiment_id: str) -> dict[str, int | float | None]:
        rows = self.store.prediction_annotations(experiment_id)
        metrics: dict[str, int | float | None] = {"prediction_anchor_count": len(rows), "completed_prediction_count": sum(all(row[f"gt_{h}"] is not None for h in HORIZONS) for row in rows)}
        for horizon in HORIZONS:
            errors = [float(row[f"error_{horizon}"]) for row in rows if row[f"gt_{horizon}"] is not None and row[f"prediction_{horizon}"] is not None]
            metrics[f"samples_{horizon}"] = len(errors)
            metrics[f"mae_{horizon}"] = sum(errors) / len(errors) if errors else None
        return metrics

    def export_experiment(self, experiment_id: str, export_root: Path) -> Path:
        output = ResearchCountService(self.store).export_experiment(experiment_id, export_root)
        rows = self.store.prediction_annotations(experiment_id)
        with (output / "prediction_ground_truth.csv").open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["anchor_time_seconds", "anchor_frame_index", "current_system_count", "prediction_slope", "prediction_10", "gt_10", "error_10", "prediction_20", "gt_20", "error_20", "prediction_30", "gt_30", "error_30", "note"])
            writer.writerows((row["anchor_time_seconds"], row["anchor_frame_index"], row["current_system_count"], row["prediction_slope"], row["prediction_10"], row["gt_10"], row["error_10"], row["prediction_20"], row["gt_20"], row["error_20"], row["prediction_30"], row["gt_30"], row["error_30"], row["note"]) for row in rows)
        summary_path = output / "experiment_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["prediction_metrics"] = self.prediction_metrics(experiment_id)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return output
