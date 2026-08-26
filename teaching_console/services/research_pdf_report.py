"""PDF rendering for child-friendly Huian research reports."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from teaching_console.services.research_report_content import ReportScreenshot, display, number, percent, research_method, research_process_summary, student_response


class PdfResearchReport:
    """Write a PDF from saved evidence; operation logs are excluded."""

    def write(self, path: Path, experiment: Mapping[str, object], counts: Sequence[Mapping[str, object]], predictions: Sequence[Mapping[str, object]], metrics: Mapping[str, object], prediction_metrics: Mapping[str, object], screenshots: Sequence[ReportScreenshot]) -> None:
        font_name = "STSong-Light"
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))
        except (KeyError, TypeError):
            pass
        styles = getSampleStyleSheet()
        title = ParagraphStyle("HuianTitle", parent=styles["Title"], fontName=font_name, fontSize=19, leading=25, alignment=TA_CENTER, textColor=colors.HexColor("#1F4E78"))
        heading = ParagraphStyle("HuianHeading", parent=styles["Heading2"], fontName=font_name, fontSize=13, leading=19, textColor=colors.HexColor("#1F4E78"), spaceBefore=12, spaceAfter=5)
        body = ParagraphStyle("HuianBody", parent=styles["BodyText"], fontName=font_name, fontSize=9.5, leading=15)
        small = ParagraphStyle("HuianSmall", parent=body, fontSize=8, leading=11)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=1.7 * cm, leftMargin=1.7 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm)
        story: list[object] = [Paragraph("慧安楼道 AI人数检测实验报告", title), Spacer(1, 0.35 * cm)]
        story += [Paragraph("一、实验基本信息", heading), self._table([["实验名称", display(experiment.get("name"), "未命名实验")], ["实验日期", display(experiment.get("experiment_date") or experiment.get("created_at"))], ["参与学生", display(experiment.get("participants"))], ["测试视频", Path(str(experiment.get("video_path") or "")).name or "尚未填写"]], body, [3.0 * cm, 13.2 * cm])]
        story += [Paragraph("二、实验目的", heading), Paragraph(display(experiment.get("purpose") or experiment.get("description")), body)]
        story.append(Paragraph("三、实验方法", heading))
        for index, method in enumerate(research_method(), 1):
            story.append(Paragraph(f"{index}. {method}", body))
        story += [Paragraph("四、实验过程", heading), Paragraph(research_process_summary(experiment, counts, predictions), body)]
        story += [Paragraph("五、实验数据", heading), self._count_table(counts, small)]
        mae = metrics.get("mae")
        metric_text = "暂无可评价样本。" if mae is None else f"MAE 为 {number(mae, 2)} 人，表示 AI 平均每次和人工结果相差 {number(mae, 2)} 个人。"
        story += [Paragraph(metric_text, body), Paragraph(f"最大误差：{number(metrics.get('max_absolute_error'), 1)} 人；完全正确率：{percent(metrics.get('exact_match_rate'))}。", body)]
        if screenshots:
            story.append(Paragraph("关键截图", heading))
            for screenshot in screenshots:
                story += [Image(str(screenshot.path), width=15.0 * cm, height=8.4 * cm, kind="proportional"), Paragraph(screenshot.caption, small), Spacer(1, 0.22 * cm)]
        story += [Paragraph("六、我的发现", heading), Paragraph(student_response(experiment.get("findings"), "实验中 AI 哪里做得不好？"), body)]
        story += [Paragraph("七、为什么会这样？", heading), Paragraph(student_response(experiment.get("cause_analysis"), "你认为造成这种结果的原因是什么？"), body)]
        story += [Paragraph("八、下一步怎么改进？", heading), Paragraph(student_response(experiment.get("next_improvement"), "如果继续研究，你准备怎样帮助 AI 做得更好？"), body)]
        if predictions:
            story += [PageBreak(), Paragraph("九、预测验证", heading), self._prediction_table(predictions, small)]
            story.append(Paragraph("；".join(f"+{horizon} 秒 MAE：{number(prediction_metrics.get(f'mae_{horizon}'), 2)} 人" for horizon in (10, 20, 30)), body))
        reflection_number = "十" if predictions else "九"
        story += [Paragraph(f"{reflection_number}、学生心得", heading), Paragraph(student_response(experiment.get("student_reflection"), "这次实验你学到了什么？"), body)]
        document.build(story)

    @staticmethod
    def _table(rows: list[list[str]], style: ParagraphStyle, widths: list[float]) -> Table:
        table = Table([[Paragraph(str(cell), style) for cell in row] for row in rows], colWidths=widths, repeatRows=0)
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C7D9")), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#D9EAF7")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        return table

    def _count_table(self, rows: Sequence[Mapping[str, object]], style: ParagraphStyle) -> Table:
        values = [["时间(秒)", "人工人数", "AI人数", "误差"]]
        for row in rows[:30]:
            values.append([number(row.get("video_time_seconds"), 1), display(row.get("ground_truth_count"), "—"), display(row.get("system_count"), "—"), number(row.get("absolute_error"), 1)])
        if len(values) == 1:
            values.append(["—", "—", "—", "暂无数据"])
        return self._header_table(values, style, [3.3 * cm, 4.0 * cm, 4.0 * cm, 4.9 * cm])

    def _prediction_table(self, rows: Sequence[Mapping[str, object]], style: ParagraphStyle) -> Table:
        values = [["预测时间", "真实人数", "预测人数", "误差"]]
        for row in rows[:30]:
            values.append([f"+{row.get('horizon_seconds')} 秒", display(row.get("ground_truth_count"), "—"), number(row.get("prediction_count"), 1), number(row.get("absolute_error"), 1)])
        return self._header_table(values, style, [4.5 * cm, 4.2 * cm, 4.2 * cm, 3.3 * cm])

    @staticmethod
    def _header_table(values: list[list[str]], style: ParagraphStyle, widths: list[float]) -> Table:
        table = Table([[Paragraph(str(cell), style) for cell in row] for row in values], colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B8C7D9")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#5B9BD5")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return table
