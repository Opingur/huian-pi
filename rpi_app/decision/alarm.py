"""基于视频时间轴的 YELLOW / RED 报警抗抖。"""

from __future__ import annotations

from typing import Mapping


class AlarmDebouncer:
    """RED 优先；激活与释放均使用输入的 source_timestamp。"""

    _PRIORITY = {"NONE": 0, "YELLOW": 1, "RED": 2}

    def __init__(self, config: Mapping[str, object]) -> None:
        self.activation_hold_seconds = float(config.get("activation_hold_seconds", 1.0))
        self.release_hold_seconds = float(config.get("release_hold_seconds", 1.5))
        self.state = "NONE"
        self._candidate: str | None = None
        self._candidate_since: float | None = None

    def update(self, source_timestamp: float, single_flow: bool, convergence: bool) -> tuple[str, str]:
        proposed = "RED" if convergence else "YELLOW" if single_flow else "NONE"
        if proposed == self.state:
            self._candidate = None
            self._candidate_since = None
        elif proposed != self._candidate:
            self._candidate = proposed
            self._candidate_since = source_timestamp
        else:
            hold = (
                self.activation_hold_seconds
                if self._PRIORITY[proposed] > self._PRIORITY[self.state]
                else self.release_hold_seconds
            )
            if self._candidate_since is not None and source_timestamp - self._candidate_since >= hold:
                self.state = proposed
                self._candidate = None
                self._candidate_since = None

        if self.state == "RED":
            return self.state, "multi_flow_convergence" if convergence else "alarm_release_hold"
        if self.state == "YELLOW":
            return self.state, "single_flow_crowd" if single_flow else "alarm_release_hold"
        return self.state, "none"
