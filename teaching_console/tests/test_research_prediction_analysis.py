from __future__ import annotations

import threading
import unittest
from pathlib import Path

from teaching_console.services.research_prediction_analysis import AnalysisCancelled, PredictionTimelineAnalysis


class Frame:
    shape = (100, 200, 3)


class Capture:
    def __init__(self, frames=31): self.frames=[Frame() for _ in range(frames)]; self.released=False
    def isOpened(self): return True
    def get(self, key): return {1: 15, 2: len(self.frames)}[key]
    def read(self): return (True, self.frames.pop(0)) if self.frames else (False, None)
    def release(self): self.released=True


class CV:
    CAP_PROP_FPS=1; CAP_PROP_FRAME_COUNT=2
    def __init__(self, capture): self.capture=capture
    def VideoCapture(self, _): return self.capture


class Tracker:
    def __init__(self): self.calls=0
    def track(self, _):
        self.calls+=1
        return [{"x1": 10, "x2": 30}, {"x1": 120, "x2": 160}]


class Flow:
    def __init__(self): self.history=[]; self.calls=[]
    def update(self, left, right, now):
        self.calls.append((left,right,now)); saved=not self.history or now-self.history[-1][0]>=1
        if saved:self.history.append((now,left,right))
        return type('Trend',(),{'total_people':left+right})(),saved


class Predictor:
    def __init__(self): self.calls=0
    def predict(self, history, current):
        self.calls+=1
        valid=len(history)>=2
        return {"prediction_slope":0.2 if valid else None,"predicted_people":{10:current+2 if valid else None,20:current+4 if valid else None,30:current+6 if valid else None}}


class AnalysisTests(unittest.TestCase):
    def build(self, frames=31):
        self.capture=Capture(frames);self.tracker=Tracker();self.flow=Flow();self.predictor=Predictor()
        return PredictionTimelineAnalysis(Path('.'),config={},cv2_loader=lambda:CV(self.capture),tracker_factory=lambda:self.tracker,flow_factory=lambda:self.flow,predictor_factory=lambda:self.predictor)

    def test_sequential_tracking_video_time_and_formal_flow_shape(self):
        result=self.build().analyze(Path('fake.mp4'))
        self.assertEqual(self.tracker.calls,31);self.assertTrue(self.capture.released)
        self.assertEqual([row['frame_index'] for row in result],[0,15,30])
        self.assertEqual([row['time_seconds'] for row in result],[0.0,1.0,2.0])
        self.assertTrue(all((row['left_count'],row['right_count'],row['current_system_count'])==(1,1,2) for row in result))
        self.assertEqual(result[0]['prediction_10'],None);self.assertEqual(result[1]['prediction_30'],8)
        self.assertEqual(self.predictor.calls,3)

    def test_cancel_and_release(self):
        event=threading.Event();event.set();service=self.build()
        with self.assertRaises(AnalysisCancelled):service.analyze(Path('fake.mp4'),cancel_event=event)
        self.assertTrue(self.capture.released);self.assertEqual(self.tracker.calls,0)

    def test_missing_model_is_explicit(self):
        service=PredictionTimelineAnalysis(Path('.'),config={"model_path":"missing.pt","confidence":.3,"tracking":{},"flow_window_seconds":30,"snapshot_interval_seconds":1,"conflict_people_per_region":4,"conflict_min_total":10,"prediction":{}})
        with self.assertRaises(FileNotFoundError):service.analyze(Path('fake.mp4'))


if __name__ == '__main__': unittest.main()
