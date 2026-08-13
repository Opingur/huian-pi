import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from vision.fire_detector import (
    FireDetector,
    FireEvidenceTracker,
    map_tile_bbox_to_frame,
    merge_fire_detections,
    tile_regions,
)


class FakeBox:
    def __init__(self, class_id, confidence, bbox):
        self.cls = np.array([class_id])
        self.conf = np.array([confidence])
        self.xyxy = np.array([bbox])


class FakeResult:
    boxes = [FakeBox(4, 0.82, [10, 20, 30, 40]), FakeBox(7, 0.74, [50, 60, 90, 100]), FakeBox(9, 0.99, [0, 0, 1, 1])]


class FakeYOLO:
    def __init__(self, _path):
        self.names = {4: "FIRE", 7: "Smoke", 9: "person"}
        self.calls = []

    def __call__(self, frame, **_kwargs):
        self.calls.append(frame.shape[:2])
        return [FakeResult()]


def evidence_result(fire: bool, detections=None):
    return {
        "fire_detected": fire, "smoke_detected": False,
        "fire_confidence": 0.8 if fire else 0.0, "smoke_confidence": 0.0,
        "detections": detections if detections is not None else ([{"class_name": "fire", "confidence": 0.8, "bbox": [10, 20, 30, 40], "source": "tile"}] if fire else []),
        "inference_ms": 12.0, "inference_sources": ["tile"] if fire else ["full"],
    }


class FireDetectorTests(unittest.TestCase):
    def test_model_with_fire_smoke_person_keeps_only_fire(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "fire_n.pt"
            model_path.touch()
            with patch("vision.fire_detector.YOLO", FakeYOLO):
                detector = FireDetector({"enabled": True, "model_path": str(model_path), "confidence": 0.35, "imgsz": 640})
                result = detector.detect(np.zeros((120, 120, 3), dtype=np.uint8))
        self.assertTrue(result["fire_detected"])
        self.assertFalse(result["smoke_detected"])
        self.assertEqual(result["fire_confidence"], 0.82)
        self.assertEqual(result["smoke_confidence"], 0.0)
        self.assertEqual([item["class_name"] for item in result["detections"]], ["fire"])

    def test_tile_bbox_maps_back_to_source_frame_for_2x2_and_3x3(self):
        self.assertEqual(map_tile_bbox_to_frame([2, 3, 10, 12], 50, 40, 128, 96), [52, 43, 60, 52])
        two_by_two = tile_regions(100, 80, 2, 2, 0.15)
        three_by_three = tile_regions(300, 180, 3, 3, 0.20)
        self.assertEqual(len(two_by_two), 4)
        self.assertEqual(len(three_by_three), 9)
        self.assertEqual(three_by_three[0][0:2], (0, 0))
        self.assertGreater(three_by_three[0][2], 100)
        self.assertEqual(map_tile_bbox_to_frame([1, 2, 11, 12], three_by_three[4][0], three_by_three[4][1], 300, 180), [91, 56, 101, 66])

    def test_overlapping_full_and_tile_boxes_merge_by_highest_confidence(self):
        merged = merge_fire_detections([
            {"class_name": "fire", "confidence": 0.91, "bbox": [10, 10, 30, 30], "source": "tile"},
            {"class_name": "fire", "confidence": 0.60, "bbox": [12, 12, 32, 32], "source": "full"},
            {"class_name": "smoke", "confidence": 0.70, "bbox": [12, 12, 32, 32], "source": "full"},
        ], 0.45)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["confidence"], 0.91)

    def test_tiled_inference_false_keeps_single_full_frame_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "fire_n.pt"
            model_path.touch()
            with patch("vision.fire_detector.YOLO", FakeYOLO):
                detector = FireDetector({"enabled": True, "model_path": str(model_path), "tiled_inference": False, "full_frame_pass": False, "confidence": 0.2, "imgsz": 640})
                result = detector.detect(np.zeros((120, 120, 3), dtype=np.uint8))
        self.assertEqual(detector.model.calls, [(120, 120)])
        self.assertEqual(result["inference_sources"], ["full"])

    def test_two_hits_in_five_inferences_confirms_fire(self):
        tracker = FireEvidenceTracker({"confirmation_hits": 2, "confirmation_window": 5, "bbox_hold_seconds": 3.0, "visual_alert_hold_seconds": 6.0}, True)
        tracker.record(evidence_result(True), 0.0)
        tracker.record(evidence_result(False), 1.0)
        tracker.record(evidence_result(True), 2.0)
        self.assertTrue(tracker.status(2.0)["vision_fire_suspected"])

    def test_bbox_hold_and_visual_alert_hold_are_separate(self):
        tracker = FireEvidenceTracker({"confirmation_hits": 2, "confirmation_window": 5, "bbox_hold_seconds": 3.0, "visual_alert_hold_seconds": 6.0}, True)
        tracker.record(evidence_result(True), 0.0)
        tracker.record(evidence_result(True), 1.0)
        tracker.record(evidence_result(False), 2.0)
        during_bbox_hold = tracker.status(3.5)
        self.assertTrue(during_bbox_hold["recent_fire_evidence"])
        self.assertTrue(during_bbox_hold["fire_bbox_temporal_hold"])
        self.assertTrue(during_bbox_hold["fire_display_detections"][0]["temporal_hold"])
        after_bbox_before_alert_expiry = tracker.status(4.1)
        self.assertTrue(after_bbox_before_alert_expiry["recent_fire_evidence"])
        self.assertTrue(after_bbox_before_alert_expiry["fire_alert_temporal_hold"])
        self.assertFalse(after_bbox_before_alert_expiry["fire_bbox_temporal_hold"])
        self.assertEqual(after_bbox_before_alert_expiry["fire_display_detections"], [])
        expired = tracker.status(7.1)
        self.assertFalse(expired["recent_fire_evidence"])
        self.assertFalse(expired["vision_fire_suspected"])
        self.assertEqual(expired["fire_display_detections"], [])

    def test_smoke_input_never_sets_visual_smoke_state_or_box(self):
        tracker = FireEvidenceTracker({"confirmation_hits": 1, "confirmation_window": 1}, True)
        smoke_only = {
            "fire_detected": False, "smoke_detected": True,
            "fire_confidence": 0.0, "smoke_confidence": 0.91,
            "detections": [{"class_name": "smoke", "confidence": 0.91, "bbox": [1, 2, 10, 12], "source": "full"}],
            "inference_ms": 12.0, "inference_sources": ["full"],
        }
        tracker.record(smoke_only, 0.0)
        status = tracker.status(0.0)
        self.assertFalse(status["smoke_detected_raw"])
        self.assertFalse(status["vision_smoke_suspected"])
        self.assertEqual(status["vision_smoke_confidence"], 0.0)
        self.assertEqual(status["fire_display_detections"], [])
    def test_no_detection_never_creates_a_bbox(self):
        tracker = FireEvidenceTracker({"bbox_hold_seconds": 3.0, "visual_alert_hold_seconds": 6.0}, True)
        tracker.record(evidence_result(False), 0.0)
        status = tracker.status(0.0)
        self.assertFalse(status["recent_fire_evidence"])
        self.assertEqual(status["fire_display_detections"], [])

    def test_enabled_missing_model_is_explicit(self):
        with self.assertRaisesRegex(FileNotFoundError, "Fire model not found"):
            FireDetector({"enabled": True, "model_path": "missing_fire_n.pt"})


if __name__ == "__main__":
    unittest.main()