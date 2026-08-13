"""慧安楼道人工标注与 status.jsonl 的轻量验证工具。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def read_status(path: str) -> list[dict]:
    with Path(path).open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def nearest(records: list[dict], target: float, tolerance: float) -> dict | None:
    candidates = [item for item in records if "source_time" in item]
    if not candidates:
        return None
    item = min(candidates, key=lambda row: abs(float(row["source_time"]) - target))
    return item if abs(float(item["source_time"]) - target) <= tolerance else None


def write_rows(path: str, columns: list[str], rows: list[dict]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: str, summary: dict) -> None:
    Path(path).with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_count(args) -> None:
    records = read_status(args.status)
    rows = []
    with Path(args.annotations).open(encoding="utf-8", newline="") as file:
        for annotation in csv.DictReader(file):
            if annotation.get("video") != args.video or not annotation.get("manual_count", "").strip():
                continue
            source_time = float(annotation["source_time"])
            match = nearest(records, source_time, args.tolerance)
            if match is not None:
                manual = int(annotation["manual_count"])
                system = int(match["total_people"])
                rows.append({"video": args.video, "source_time": source_time, "manual_count": manual, "system_count": system, "abs_error": abs(manual - system)})
    errors = [row["abs_error"] for row in rows]
    summary = {"sample_count": len(rows), "mae": None if not errors else sum(errors) / len(errors), "max_abs_error": None if not errors else max(errors), "exact_match_ratio": None if not errors else sum(error == 0 for error in errors) / len(errors)}
    write_rows(args.output, ["video", "source_time", "manual_count", "system_count", "abs_error"], rows)
    write_summary(args.output, summary)


def validate_prediction(args) -> None:
    records = read_status(args.status)
    rows = []
    for record in records:
        if not record.get("prediction_valid"):
            continue
        source_time = float(record["source_time"])
        for horizon in (10, 20, 30):
            predicted = record.get(f"predicted_people_{horizon}s")
            actual = nearest(records, source_time + horizon, args.tolerance)
            if predicted is not None and actual is not None:
                rows.append({"video": args.video, "source_time": source_time, "horizon_seconds": horizon, "predicted_people": predicted, "actual_people": actual["total_people"], "abs_error": abs(float(predicted) - float(actual["total_people"]))})
    summary = {str(horizon): {"sample_count": len(group), "mae": None if not group else sum(item["abs_error"] for item in group) / len(group)} for horizon, group in ((h, [row for row in rows if row["horizon_seconds"] == h]) for h in (10, 20, 30))}
    write_rows(args.output, ["video", "source_time", "horizon_seconds", "predicted_people", "actual_people", "abs_error"], rows)
    write_summary(args.output, summary)


def validate_alarm(args) -> None:
    records = read_status(args.status)
    rows = []
    with Path(args.annotations).open(encoding="utf-8", newline="") as file:
        for item in csv.DictReader(file):
            if item.get("video") != args.video or not item.get("expected_alarm", "").strip():
                continue
            start, end = float(item["start_time"]), float(item["end_time"])
            alarms = {str(record.get("visual_alarm")) for record in records if start <= float(record.get("source_time", -1)) <= end}
            expected = item["expected_alarm"].strip().upper()
            rows.append({"scenario": item["scenario"], "expected_alarm": expected, "observed_alarms": ";".join(sorted(alarms)), "correct": expected in alarms})
    summary = {"scenario_count": len(rows), "correct_count": sum(row["correct"] for row in rows), "correct_ratio": None if not rows else sum(row["correct"] for row in rows) / len(rows)}
    write_rows(args.output, ["scenario", "expected_alarm", "observed_alarms", "correct"], rows)
    write_summary(args.output, summary)


def validate_direction(args) -> None:
    with Path(args.system).open(encoding="utf-8", newline="") as file:
        system = [row for row in csv.DictReader(file) if row.get("video") == args.video]
    rows = []
    with Path(args.annotations).open(encoding="utf-8", newline="") as file:
        for item in csv.DictReader(file):
            if item.get("video") != args.video or not item.get("manual_direction", "").strip() or not item.get("system_track_id", "").strip():
                continue
            observed = {row["system_direction"] for row in system if row.get("system_track_id") == item["system_track_id"] and float(item["start_time"]) <= float(row["source_time"]) <= float(item["end_time"])}
            expected = item["manual_direction"].strip()
            rows.append({"track_reference": item.get("track_reference", ""), "manual_direction": expected, "observed_directions": ";".join(sorted(observed)), "correct": expected in observed})
    summary = {"sample_count": len(rows), "correct_count": sum(row["correct"] for row in rows), "accuracy": None if not rows else sum(row["correct"] for row in rows) / len(rows)}
    write_rows(args.output, ["track_reference", "manual_direction", "observed_directions", "correct"], rows)
    write_summary(args.output, summary)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("count", validate_count), ("prediction", validate_prediction), ("alarm", validate_alarm), ("direction", validate_direction)):
        command = sub.add_parser(name)
        command.add_argument("--video", required=True)
        command.add_argument("--status", required=True)
        command.add_argument("--output", required=True)
        command.add_argument("--tolerance", type=float, default=1.1)
        if name != "prediction":
            command.add_argument("--annotations", required=True)
        if name == "direction":
            command.add_argument("--system", required=True)
        command.set_defaults(handler=handler)
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
