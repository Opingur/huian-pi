"""基于固定区域占用历史的短时拥堵趋势预测。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class CrowdPredictor:
    """用最小二乘一阶趋势拟合预测未来短时人员占用。"""

    def __init__(
        self,
        config: dict[str, Any],
        crowd_calibration: dict[str, Any] | None = None,
    ) -> None:
        self.enabled = bool(config.get("enabled", True))
        self.window_seconds = float(config.get("window_seconds", 15))
        self.min_samples = int(config.get("min_samples", 5))
        self.min_history_seconds = float(config.get("min_history_seconds", 8))
        self.horizons = tuple(int(value) for value in config.get("horizons", [10, 20, 30]))
        self.max_eta_seconds = float(config.get("max_eta_seconds", 120))
        calibration = crowd_calibration or {}
        threshold = calibration.get("danger_people_threshold")
        self.calibrated = (
            bool(calibration.get("calibrated", False))
            and isinstance(threshold, int)
            and not isinstance(threshold, bool)
            and threshold > 0
        )
        # Valid only after a controlled real-stair experiment; no fallback exists.
        self.danger_people_threshold = int(threshold) if self.calibrated else None

    def _risk_for_people(self, people: float) -> str:
        if people < 8:
            return "NORMAL"
        if self.danger_people_threshold is None or people < self.danger_people_threshold:
            return "WARNING"
        return "DANGER"

    def _empty_forecast(self) -> dict[str, object]:
        return {
            "prediction_valid": False,
            "prediction_slope": None,
            "predicted_people": {horizon: None for horizon in self.horizons},
            "predicted_risk": {horizon: None for horizon in self.horizons},
            "time_to_warning": None,
            "time_to_danger": None,
            "crowd_calibrated": self.calibrated,
            "danger_people_threshold": self.danger_people_threshold,
        }

    def predict(
        self,
        history: Iterable[tuple[float, int, int]],
        current_people: int,
    ) -> dict[str, object]:
        """根据 PeopleFlowAnalyzer 的同一份快照历史返回透明趋势预测。

        斜率是固定区域占用人数时间序列的变化趋势，不是人员移动速度。
        """
        forecast = self._empty_forecast()
        if not self.enabled:
            return forecast

        snapshots = list(history)
        if not snapshots:
            return forecast
        latest_time = snapshots[-1][0]
        samples = [
            snapshot
            for snapshot in snapshots
            if snapshot[0] >= latest_time - self.window_seconds
        ]
        if len(samples) < self.min_samples:
            return forecast
        if samples[-1][0] - samples[0][0] < self.min_history_seconds:
            return forecast

        start_time = samples[0][0]
        times = [sample[0] - start_time for sample in samples]
        totals = [sample[1] + sample[2] for sample in samples]
        mean_time = sum(times) / len(times)
        mean_total = sum(totals) / len(totals)
        denominator = sum((value - mean_time) ** 2 for value in times)
        if denominator <= 0:
            return forecast
        slope = sum(
            (time_value - mean_time) * (total - mean_total)
            for time_value, total in zip(times, totals)
        ) / denominator

        predicted_people = {
            horizon: round(max(0.0, float(current_people) + slope * horizon), 1)
            for horizon in self.horizons
        }
        forecast.update(
            {
                "prediction_valid": True,
                "prediction_slope": round(slope, 3),
                "predicted_people": predicted_people,
                "predicted_risk": {
                    horizon: self._risk_for_people(people)
                    for horizon, people in predicted_people.items()
                },
            }
        )
        if slope <= 0:
            return forecast

        warning_threshold = 8
        warning_eta = 0.0 if current_people >= warning_threshold else (warning_threshold - current_people) / slope
        if warning_eta <= self.max_eta_seconds:
            forecast["time_to_warning"] = round(warning_eta, 1)

        if self.danger_people_threshold is not None:
            danger_eta = (
                0.0
                if current_people >= self.danger_people_threshold
                else (self.danger_people_threshold - current_people) / slope
            )
            if danger_eta <= self.max_eta_seconds:
                forecast["time_to_danger"] = round(danger_eta, 1)
        return forecast
