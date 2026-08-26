"""Pure workflow helpers for the student-facing prediction experiment.

The formal predictor creates and freezes ``prediction_annotations`` before a
student starts the verification activity.  This module deliberately only
selects and presents that evidence; it never invokes YOLO, tracking, or the
predictor again.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from teaching_console.services.research_prediction_service import HORIZONS, annotation_horizons


def validation_cards(
    annotation: Mapping[str, Any], *, fps: float, video_duration_seconds: float
) -> list[dict[str, float | int | bool | object]]:
    """Describe the three frozen prediction targets against the real video.

    A card is unavailable when the source video cannot contain its target
    frame.  The caller can therefore suppress its input controls instead of
    asking a child to invent an answer for a non-existent future moment.
    """
    duration = max(0.0, float(video_duration_seconds))
    safe_fps = max(0.0, float(fps))
    anchor = float(annotation["anchor_time_seconds"])
    cards: list[dict[str, float | int | bool | object]] = []
    for slot, horizon in zip(HORIZONS, annotation_horizons(annotation)):
        target_time = anchor + float(horizon)
        # sqlite3.Row is intentionally supported alongside ordinary mappings.
        prediction = annotation[f"prediction_{slot}"]
        available = prediction is not None and target_time <= duration + 1e-6 and safe_fps > 0
        cards.append(
            {
                "slot": slot,
                "horizon_seconds": int(horizon),
                "target_time_seconds": target_time,
                "frame_index": int(round(target_time * safe_fps)),
                "prediction": prediction,
                "available": available,
            }
        )
    return cards


def select_frozen_prediction_anchor(
    annotations: Sequence[Mapping[str, Any]],
    *,
    selected_time_seconds: float,
    video_duration_seconds: float,
    tolerance_seconds: float = 0.51,
) -> Mapping[str, Any] | None:
    """Return the frozen anchor at a selected video time, or ``None``.

    A tight, explicit tolerance permits a student to stop a 15 fps video on
    the displayed second without silently replacing their choice with a
    distant prediction point.
    """
    selected = float(selected_time_seconds)
    candidates = [
        annotation
        for annotation in annotations
        if abs(float(annotation["anchor_time_seconds"]) - selected) <= tolerance_seconds
        and any(card["available"] for card in validation_cards(
            annotation, fps=1.0, video_duration_seconds=video_duration_seconds
        ))
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda annotation: abs(float(annotation["anchor_time_seconds"]) - selected))
