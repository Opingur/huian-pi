"""Markdown-only research record for a child-facing AI growth experiment."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from teaching_console.services.ai_growth_excel_data import AIGrowthExcelData
from teaching_console.services.ai_growth_experiment_service import summarize_growth
from teaching_console.services.ai_growth_word_report import AIGrowthWordReport
from teaching_console.services.research_count_service import safe_export_name
from teaching_console.services.research_store import ResearchStore


@dataclass(frozen=True)
class AIGrowthRecordExport:
    directory: Path
    markdown_path: Path
    summary_path: Path
    docx_path: Path
    xlsx_path: Path


class AIGrowthRecordExporter:
    """Export saved child evidence only; it never reruns detection or training."""

    def __init__(self, store: ResearchStore) -> None:
        self.store = store

    def export(
        self,
        experiment_id: str,
        project_ids: Sequence[str],
        *,
        ab_result: Mapping[str, object] | None = None,
        output_root: Path | None = None,
    ) -> AIGrowthRecordExport:
        experiment = self.store.get_experiment(experiment_id)
        if experiment is None:
            raise KeyError(experiment_id)
        project_rows = []
        for project_id in dict.fromkeys(project_ids):
            project = self.store.get_detection_annotation_project(project_id)
            if project is not None:
                project_rows.append(dict(project))
        if not project_rows:
            raise ValueError("还没有可保存的 AI 成长实验视频。")

        root = Path(output_root or self.store.project_root / "huian_research_records")
        directory = self._directory(root, dict(experiment))
        directory.mkdir(parents=True, exist_ok=True)
        evidence = self._project_evidence(project_rows)
        frames = self._frame_statistics(project_rows)
        reason_text = self._reason_text(evidence)
        verification = self._verification(ab_result)
        payload = {
            "experiment": dict(experiment),
            "projects": evidence,
            "frame_statistics": frames,
            "ab_result": dict(ab_result) if ab_result is not None else None,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        summary_path = directory / "AI成长实验摘要.json"
        markdown_path = directory / "AI成长实验记录.md"
        docx_path = directory / "AI成长实验记录.docx"
        xlsx_path = directory / "AI成长实验统计数据.xlsx"
        summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(self._markdown(dict(experiment), evidence, ab_result), encoding="utf-8")
        AIGrowthWordReport().write(docx_path, dict(experiment), evidence, frames, reason_text, verification)
        AIGrowthExcelData().write(xlsx_path, dict(experiment), evidence, frames, verification)
        self.store.log_activity(experiment_id, "export_ai_growth_record", "导出 AI 成长实验 Word 记录和 Excel 统计数据")
        return AIGrowthRecordExport(directory, markdown_path, summary_path, docx_path, xlsx_path)

    def _project_evidence(self, projects: Sequence[dict[str, object]]) -> list[dict[str, object]]:
        evidence = []
        for project in projects:
            frames = [dict(row) for row in self.store.detection_frame_annotations(str(project["id"]))]
            kept = [row for row in frames if row["kept"]]
            completed = [row for row in kept if row["annotation_completed"]]
            reasons = Counter(str(row["student_reason"]) for row in completed if str(row["student_reason"]).strip())
            evidence.append({
                "purpose": "困难帧实验视频",
                "source_video": str(project["source_video"]),
                "source_video_name": Path(str(project["source_video"])).name,
                "candidate_frames": len(frames),
                "kept_frames": len(kept),
                "completed_frames": len(completed),
                "person_boxes": sum(len(self.store.detection_person_boxes(str(row["id"]))) for row in completed),
                "student_reasons": dict(reasons),
            })
        return evidence

    def _frame_statistics(self, projects: Sequence[dict[str, object]]) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for project in projects:
            source_name = Path(str(project["source_video"])).name
            for frame in self.store.detection_frame_annotations(str(project["id"])):
                completed = bool(frame["annotation_completed"])
                human_count = len(self.store.detection_person_boxes(str(frame["id"]))) if completed else None
                system_count = frame["system_count"]
                absolute_error = abs(int(system_count) - human_count) if system_count is not None and human_count is not None else None
                rows.append({
                    "source_video_name": source_name,
                    "frame_index": int(frame["frame_index"]),
                    "video_time_seconds": float(frame["video_time_seconds"]),
                    "system_count": system_count,
                    "human_count": human_count,
                    "absolute_error": absolute_error,
                    "annotation_completed": completed,
                    "student_reason": str(frame["student_reason"] or ""),
                    "recommendation_reasons": str(frame["recommendation_reasons"] or ""),
                })
        return sorted(rows, key=lambda row: (str(row["source_video_name"]), int(row["frame_index"])))

    @staticmethod
    def _reason_text(evidence: Sequence[Mapping[str, object]]) -> str:
        reasons = Counter()
        for row in evidence:
            reasons.update(dict(row["student_reasons"]))
        return "；".join(f"{reason}：{count} 张" for reason, count in reasons.items()) or "孩子还没有填写困难原因。"

    @staticmethod
    def _verification(ab_result: Mapping[str, object] | None) -> str:
        if ab_result is None:
            return "成长后的模型尚未导入，因此本次记录只保存了困难图片与人工框选。完成真实训练并导入 best.pt 后，可以再次导出，补充小测图片验证结果。"
        summary = summarize_growth(ab_result)
        return (
            f"成长前平均每张小测图片相差 {summary.baseline_mae:.2f} 人；"
            f"成长后相差 {summary.candidate_mae:.2f} 人。\n\n{summary.message}"
        )
    @staticmethod
    def _directory(root: Path, experiment: Mapping[str, object]) -> Path:
        date = str(experiment.get("experiment_date") or experiment.get("created_at") or "")[:10] or "未填写日期"
        stem = f"{safe_export_name(str(experiment.get('name') or ''), str(experiment['id']))}_{date}"
        candidate = root / stem
        marker = candidate / "AI成长实验摘要.json"
        if not candidate.exists():
            return candidate
        try:
            if json.loads(marker.read_text(encoding="utf-8"))["experiment"]["id"] == experiment["id"]:
                return candidate
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
        return root / f"{stem}_{str(experiment['id'])[:8]}"

    @staticmethod
    def _markdown(
        experiment: Mapping[str, object], evidence: Sequence[Mapping[str, object]], ab_result: Mapping[str, object] | None,
    ) -> str:
        table = "\n".join(
            "| {purpose} | {video} | {kept} | {completed} | {boxes} |".format(
                purpose=str(row["purpose"]),
                video=Path(str(row["source_video"])).name,
                kept=row["kept_frames"], completed=row["completed_frames"], boxes=row["person_boxes"],
            ) for row in evidence
        )
        reasons = Counter()
        for row in evidence:
            reasons.update(dict(row["student_reasons"]))
        reason_text = "；".join(f"{reason}：{count} 张" for reason, count in reasons.items()) or "孩子还没有填写困难原因。"
        if ab_result is None:
            verification = "成长后的模型尚未导入，因此本次记录只保存了困难图片与人工框选。完成真实训练并导入 best.pt 后，可以再次导出，补充小测图片验证结果。"
        else:
            summary = summarize_growth(ab_result)
            verification = (
                f"成长前平均每张小测图片相差 {summary.baseline_mae:.2f} 人；"
                f"成长后相差 {summary.candidate_mae:.2f} 人。\n\n{summary.message}"
            )
        return f"""# AI 成长实验研究记录

## 一、实验名称

{experiment.get('name') or '未命名 AI 成长实验'}

## 二、实验目的

{experiment.get('purpose') or '帮助 AI 更准确地识别楼道画面中的人。'}

## 三、参与人员与时间

- 参与学生：{experiment.get('participants') or '待填写'}
- 实验日期：{experiment.get('experiment_date') or experiment.get('created_at') or '待填写'}

## 四、孩子完成的工作

1. 从视频中找出 AI 容易数错的困难画面；
2. 观察画面为什么难；
3. 用鼠标框出每一个人，给 AI 正确答案；
4. 在没有参与学习的小测图片上检查 AI 是否真的进步。

## 五、视频与人工框选记录

| 图片用途 | 视频 | 保留图片 | 已完成框选 | 人体框总数 |
| --- | --- | ---: | ---: | ---: |
{table}

孩子观察到的困难原因：{reason_text}

## 六、AI 成长验证

{verification}

## 七、下一步

继续补充不同光线、遮挡和人群密集场景的困难图片，再进行一次独立小测图片验证。
"""
