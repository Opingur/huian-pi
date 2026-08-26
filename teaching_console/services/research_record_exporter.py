"""Create reusable Markdown, Word, PDF and Excel research records from SQLite evidence."""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from teaching_console.services.research_count_service import ResearchCountService, safe_export_name
from teaching_console.services.research_docx_report import WordResearchReport
from teaching_console.services.research_excel_report import ExcelResearchData
from teaching_console.services.research_pdf_report import PdfResearchReport
from teaching_console.services.research_prediction_service import ResearchPredictionService
from teaching_console.services.research_report_content import ReportScreenshot, display, number, percent, prediction_rows, prepare_screenshots, research_method, research_process_summary, student_response
from teaching_console.services.research_store import ResearchStore


@dataclass(frozen=True)
class ResearchRecordExport:
    directory: Path
    markdown_path: Path
    data_path: Path
    result_path: Path
    docx_path: Path
    pdf_path: Path
    xlsx_path: Path
    screenshots: tuple[ReportScreenshot, ...]


def _record_date(experiment: Mapping[str, object]) -> str:
    explicit = str(experiment.get("experiment_date") or "").strip()
    if explicit:
        return re.sub(r"[^0-9A-Za-z._-]+", "_", explicit).strip("._") or "未填写日期"
    created = str(experiment.get("created_at") or "")
    return created[:10] if len(created) >= 10 else "未填写日期"


class ResearchRecordExporter:
    """Create study materials strictly from stored evidence, without rerunning inference."""

    def __init__(self, store: ResearchStore, *, model_name: str = "models/yolov8n.pt") -> None:
        self.store = store
        self.model_name = model_name

    def export(self, experiment_id: str, output_root: Path | None = None) -> ResearchRecordExport:
        experiment_row = self.store.get_experiment(experiment_id)
        if experiment_row is None:
            raise KeyError(experiment_id)
        experiment = dict(experiment_row)
        root = Path(output_root or self.store.project_root / "huian_research_records")
        directory = self._directory(root, experiment)
        screenshots_dir = directory / "关键截图"
        raw_data_dir = directory / "原始数据"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        raw_data_dir.mkdir(parents=True, exist_ok=True)

        self.store.log_activity(experiment_id, "export_research_record", "生成我的实验报告")
        counts = [dict(row) for row in self.store.annotations(experiment_id)]
        predictions = prediction_rows(self.store, experiment_id)
        count_metrics = ResearchCountService(self.store).metrics(experiment_id)
        prediction_metrics = ResearchPredictionService(self.store).prediction_metrics(experiment_id)
        growth_experiments = [dict(row) for row in self.store.model_experiments_for_research(experiment_id)]
        screenshots = tuple(prepare_screenshots(experiment, counts, predictions, screenshots_dir))

        data_path = raw_data_dir / "数据记录.csv"
        prediction_data_path = raw_data_dir / "预测验证数据.csv"
        result_path = raw_data_dir / "研究记录摘要.json"
        markdown_path = raw_data_dir / "实验记录.md"
        self._write_data_csv(data_path, counts)
        self._write_prediction_csv(prediction_data_path, predictions)
        result_path.write_text(json.dumps({
            "experiment_id": experiment_id,
            "experiment": experiment,
            "count_metrics": count_metrics,
            "prediction_metrics": prediction_metrics,
            "prediction_records": predictions,
            "ai_growth_experiments": growth_experiments,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_path.write_text(self._markdown(experiment, counts, predictions, count_metrics, prediction_metrics), encoding="utf-8")

        docx_path = directory / "实验报告.docx"
        pdf_path = directory / "实验报告.pdf"
        xlsx_path = directory / "实验数据.xlsx"
        WordResearchReport().write(docx_path, experiment, counts, predictions, count_metrics, prediction_metrics, screenshots)
        PdfResearchReport().write(pdf_path, experiment, counts, predictions, count_metrics, prediction_metrics, screenshots)
        ExcelResearchData().write(xlsx_path, experiment, counts, predictions, count_metrics, prediction_metrics)
        return ResearchRecordExport(directory, markdown_path, data_path, result_path, docx_path, pdf_path, xlsx_path, screenshots)

    @staticmethod
    def _write_data_csv(path: Path, rows: list[dict[str, object]]) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["序号", "视频时间（秒）", "帧号", "人工真实人数", "AI检测人数", "相差人数", "观察记录"])
            for row in rows:
                writer.writerow([row.get("sample_index"), row.get("video_time_seconds"), row.get("frame_index"), row.get("ground_truth_count"), row.get("system_count"), row.get("absolute_error"), row.get("note", "")])

    @staticmethod
    def _write_prediction_csv(path: Path, rows: list[dict[str, object]]) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(["预测起点（秒）", "预测时长（秒）", "AI预测人数", "人工真实人数", "相差人数"])
            for row in rows:
                writer.writerow([row.get("anchor_time_seconds"), row.get("horizon_seconds"), row.get("prediction_count"), row.get("ground_truth_count"), row.get("absolute_error")])

    @staticmethod
    def _directory(root: Path, experiment: Mapping[str, object]) -> Path:
        safe_name = safe_export_name(str(experiment.get("name") or ""), str(experiment["id"]))
        record_date = _record_date(experiment)
        base = f"{safe_name}_{record_date}"
        candidate = root / base

        def owns(path: Path) -> bool:
            for relative in (Path("原始数据") / "研究记录摘要.json", Path("实验结果") / "研究记录摘要.json"):
                try:
                    payload = json.loads((path / relative).read_text(encoding="utf-8"))
                    if payload.get("experiment_id") == experiment["id"]:
                        return True
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    continue
            return False

        legacy_candidate = root / f"{record_date}_{safe_name}"
        if legacy_candidate.exists() and owns(legacy_candidate):
            return legacy_candidate
        if not candidate.exists() or owns(candidate):
            return candidate
        candidate = root / f"{base}_{str(experiment['id'])[:8]}"
        suffix = 2
        while candidate.exists() and not owns(candidate):
            candidate = root / f"{base}_{str(experiment['id'])[:8]}_{suffix}"
            suffix += 1
        return candidate

    def _markdown(
        self,
        experiment: Mapping[str, object],
        counts: list[dict[str, object]],
        predictions: list[dict[str, object]],
        metrics: Mapping[str, object],
        prediction_metrics: Mapping[str, object],
    ) -> str:
        count_rows = "\n".join(
            "| {time} | {human} | {ai} | {error} |".format(
                time=number(row.get("video_time_seconds"), 1),
                human=display(row.get("ground_truth_count"), "—"),
                ai=display(row.get("system_count"), "—"),
                error=number(row.get("absolute_error"), 1),
            ) for row in counts
        ) or "| — | — | — | 暂无数据 |"
        prediction_rows_text = "\n".join(
            "| +{horizon} 秒 | {truth} | {prediction} | {error} |".format(
                horizon=row.get("horizon_seconds"),
                truth=display(row.get("ground_truth_count"), "—"),
                prediction=number(row.get("prediction_count"), 1),
                error=number(row.get("absolute_error"), 1),
            ) for row in predictions
        ) or "| — | — | — | 暂无数据 |"
        method_rows = "\n".join(f"{index}. {item}" for index, item in enumerate(research_method(), 1))
        prediction_section = ""
        if predictions:
            prediction_summary = "；".join(
                f"+{horizon} 秒 MAE：{number((prediction_metrics or {}).get(f'mae_{horizon}'), 2)} 人"
                for horizon in (10, 20, 30)
            )
            prediction_section = f"""
## 九、预测验证

| 预测时间 | 真实人数 | 预测人数 | 误差 |
| --- | ---: | ---: | ---: |
{prediction_rows_text}

{prediction_summary}
"""
        return f"""# 慧安楼道 AI人数检测实验报告

## 一、实验基本信息

- 实验名称：{display(experiment.get('name'), '未命名实验')}
- 实验日期：{display(experiment.get('experiment_date') or experiment.get('created_at'))}
- 参与学生：{display(experiment.get('participants'))}
- 测试视频：{Path(str(experiment.get('video_path') or '')).name or '尚未填写'}

## 二、实验目的

{display(experiment.get('purpose') or experiment.get('description'))}

## 三、实验方法

{method_rows}

## 四、实验过程

{research_process_summary(experiment, counts, predictions)}

## 五、实验数据

| 时间（秒） | 人工人数 | AI人数 | 误差 |
| ---: | ---: | ---: | ---: |
{count_rows}

- 标注任务总数：{metrics.get('total_tasks', 0)}
- 已完成人工标注：{metrics.get('completed_ground_truth', 0)}
- 可评价样本：{metrics.get('evaluated_samples', 0)}
- MAE：{number(metrics.get('mae'), 2)} 人，表示 AI 平均每次和人工结果相差几个人。
- 最大误差：{number(metrics.get('max_absolute_error'), 1)} 人。
- 完全正确率：{percent(metrics.get('exact_match_rate'))}。

## 六、我的发现

{student_response(experiment.get('findings'), '实验中 AI 哪里做得不好？')}

## 七、为什么会这样？

{student_response(experiment.get('cause_analysis'), '你认为造成这种结果的原因是什么？')}

## 八、下一步怎么改进？

{student_response(experiment.get('next_improvement'), '如果继续研究，你准备怎样帮助 AI 做得更好？')}
{prediction_section}
## 十、学生心得

{student_response(experiment.get('student_reflection'), '这次实验你学到了什么？')}
"""
