"""Child-facing summaries for the real AI growth experiment.

The functions here do not train or infer.  They make the existing, real
dataset split and A/B results understandable in the Tkinter teaching page.
Keeping this interpretation separate makes it straightforward to test that we
never describe a non-improvement as an AI improvement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


CHILD_DIFFICULTY_REASONS: tuple[str, ...] = (
    "人太多重叠",
    "画面太暗",
    "人离得太远",
    "有人被遮挡",
)

SPLIT_LABELS = {
    "train": "练习图片（给 AI 学习）",
    "val": "老师检查图片（训练中检查）",
    "test": "小测图片（AI 从没见过）",
}


@dataclass(frozen=True)
class GrowthSummary:
    baseline_mae: float
    candidate_mae: float
    improvement: float
    message: str


@dataclass(frozen=True)
class ChallengeFeedback:
    frame_id: str
    ground_truth_count: int
    baseline_count: int
    candidate_count: int
    baseline_error: float
    candidate_error: float
    improvement: float
    message: str


def split_label(split_name: str) -> str:
    try:
        return SPLIT_LABELS[split_name]
    except KeyError as error:
        raise ValueError(f"未知实验图片类型：{split_name}") from error


def required_split_message(assignments: Mapping[str, str]) -> str | None:
    """Explain the missing source-video split without exposing training jargon."""
    present = set(assignments.values())
    missing = [split for split in ("train", "val", "test") if split not in present]
    if not missing:
        return None
    names = "、".join(split_label(split).split("（", 1)[0] for split in missing)
    return f"还需要准备：{names}。三组图片必须来自不同视频，才能公平验证 AI 是否真的进步。"


def summarize_growth(result: Mapping[str, object]) -> GrowthSummary:
    """Turn real A/B count-MAE output into an honest child-readable conclusion."""
    baseline = result.get("baseline")
    candidate = result.get("candidate")
    if not isinstance(baseline, Mapping) or not isinstance(candidate, Mapping):
        raise ValueError("A/B 结果缺少成长前或成长后的统计数据。")
    before = baseline.get("count_mae")
    after = candidate.get("count_mae")
    if before is None or after is None:
        raise ValueError("A/B 结果没有可用的人工标注样本。")
    before_value, after_value = float(before), float(after)
    improvement = before_value - after_value
    if improvement > 1e-9:
        message = f"AI 进步了：平均每张小测图片少数错 {improvement:.2f} 人。"
    elif improvement < -1e-9:
        message = f"这次没有进步：成长后的 AI 平均多错了 {-improvement:.2f} 人，需要继续补充困难图片。"
    else:
        message = "这次结果没有变化：两次平均误差相同，还需要更多不同场景的困难图片。"
    return GrowthSummary(before_value, after_value, improvement, message)


def challenge_feedback_rows(samples: Sequence[Mapping[str, object]]) -> tuple[ChallengeFeedback, ...]:
    """Create per-frame feedback from the exact shared-GT A/B samples."""
    rows: list[ChallengeFeedback] = []
    for sample in samples:
        baseline = sample.get("baseline")
        candidate = sample.get("candidate")
        if not isinstance(baseline, Mapping) or not isinstance(candidate, Mapping):
            raise ValueError("小测图片结果缺少模型统计。")
        before_error = float(baseline["absolute_count_error"])
        after_error = float(candidate["absolute_count_error"])
        improvement = before_error - after_error
        if improvement > 1e-9:
            message = f"少数错 {improvement:.0f} 人"
        elif improvement < -1e-9:
            message = f"多错了 {-improvement:.0f} 人"
        else:
            message = "结果相同"
        rows.append(
            ChallengeFeedback(
                frame_id=str(sample["frame_id"]),
                ground_truth_count=int(sample["ground_truth_count"]),
                baseline_count=int(baseline["model_count"]),
                candidate_count=int(candidate["model_count"]),
                baseline_error=before_error,
                candidate_error=after_error,
                improvement=improvement,
                message=message,
            )
        )
    return tuple(rows)
