"""Track-history based running-event detector.

This is an explainable candidate threshold, not a trained behaviour classifier.
It consumes source-time samples from the formal ByteTrack stream and never
changes the global crowd/fire risk state.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import hypot
from typing import Mapping


@dataclass
class _TrackState:
    samples: deque[tuple[float, float, float, float]]
    high_since: float | None = None
    low_since: float | None = None
    running: bool = False
    running_since: float | None = None


class RunningDetector:
    """Confirm sustained, scale-normalised motion from stable Track IDs."""

    def __init__(self, config: Mapping[str, object] | None = None) -> None:
        settings = dict(config or {})
        self.window_seconds = float(settings.get("window_seconds", 0.8))
        self.enter_threshold = float(settings.get("enter_threshold", 1.2))
        self.exit_threshold = float(settings.get("exit_threshold", 0.65))
        self.confirm_seconds = float(settings.get("confirm_seconds", 0.35))
        self.release_seconds = float(settings.get("release_seconds", 0.45))
        self.minimum_track_history = float(settings.get("minimum_track_history", 0.5))
        self.max_sample_speed = float(settings.get("max_sample_speed", 5.0))
        if min(self.window_seconds, self.enter_threshold, self.exit_threshold, self.confirm_seconds, self.minimum_track_history) <= 0:
            raise ValueError("running_detection thresholds must be positive")
        if self.exit_threshold >= self.enter_threshold:
            raise ValueError("running_detection.exit_threshold must be lower than enter_threshold")
        self._tracks: dict[int, _TrackState] = {}

    @staticmethod
    def _sample(track: Mapping[str, object], source_time: float) -> tuple[float, float, float, float]:
        x1, y1, x2, y2 = (float(track[name]) for name in ("x1", "y1", "x2", "y2"))
        return source_time, (x1 + x2) / 2.0, (y1 + y2) / 2.0, max(1.0, y2 - y1)

    @staticmethod
    def _speed(samples: deque[tuple[float, float, float, float]]) -> float:
        first, last = samples[0], samples[-1]
        elapsed = last[0] - first[0]
        if elapsed <= 0:
            return 0.0
        scale = max(1.0, (first[3] + last[3]) / 2.0)
        return hypot(last[1] - first[1], last[2] - first[2]) / elapsed / scale

    def update(self, tracks: list[Mapping[str, object]], source_time: float) -> dict[int, dict[str, object]]:
        """Return local running evidence for each current track.

        An implausibly large adjacent jump is discarded rather than accepted as
        evidence.  This protects the state machine from a one-frame ID jump.
        """
        source_time = float(source_time)
        seen: set[int] = set()
        result: dict[int, dict[str, object]] = {}
        for track in tracks:
            track_id = int(track["track_id"])
            seen.add(track_id)
            state = self._tracks.setdefault(track_id, _TrackState(deque()))
            sample = self._sample(track, source_time)
            if not state.samples or sample[0] > state.samples[-1][0]:
                if state.samples:
                    previous = state.samples[-1]
                    delta_t = sample[0] - previous[0]
                    adjacent_speed = hypot(sample[1] - previous[1], sample[2] - previous[2]) / max(delta_t, 1e-6) / max(1.0, (sample[3] + previous[3]) / 2.0)
                    if adjacent_speed <= self.max_sample_speed:
                        state.samples.append(sample)
                else:
                    state.samples.append(sample)
            cutoff = source_time - self.window_seconds
            while len(state.samples) > 1 and state.samples[0][0] < cutoff:
                state.samples.popleft()
            history_seconds = state.samples[-1][0] - state.samples[0][0] if len(state.samples) > 1 else 0.0
            speed = self._speed(state.samples) if history_seconds >= self.minimum_track_history else 0.0
            if history_seconds < self.minimum_track_history:
                state.high_since = None
                state.low_since = None
            elif not state.running:
                state.low_since = None
                state.high_since = source_time if speed >= self.enter_threshold and state.high_since is None else state.high_since
                if speed < self.enter_threshold:
                    state.high_since = None
                if state.high_since is not None and source_time - state.high_since >= self.confirm_seconds:
                    state.running = True
                    state.running_since = state.high_since
                    state.low_since = None
            else:
                state.high_since = None
                state.low_since = source_time if speed <= self.exit_threshold and state.low_since is None else state.low_since
                if speed > self.exit_threshold:
                    state.low_since = None
                if state.low_since is not None and source_time - state.low_since >= self.release_seconds:
                    state.running = False
                    state.running_since = None
                    state.low_since = None
            duration = 0.0 if not state.running or state.running_since is None else source_time - state.running_since
            result[track_id] = {
                "running": state.running,
                "normalized_speed": round(speed, 3),
                "running_duration": round(max(0.0, duration), 3),
                "history_seconds": round(history_seconds, 3),
            }
        stale_before = source_time - max(self.window_seconds, self.minimum_track_history) * 2.0
        for track_id, state in list(self._tracks.items()):
            if track_id not in seen and (not state.samples or state.samples[-1][0] < stale_before):
                del self._tracks[track_id]
        return result

def aggregate_running(running_by_id: Mapping[int, Mapping[str, object]]) -> dict[str, object]:
    """Build the small system-level event without leaking per-track data to UART."""
    track_ids = sorted(int(track_id) for track_id, evidence in running_by_id.items() if bool(evidence.get("running")))
    return {
        "running_event": bool(track_ids),
        "running_count": len(track_ids),
        "running_track_ids": track_ids,
    }