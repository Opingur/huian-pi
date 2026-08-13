import unittest

import numpy as np

from ui.fire_visualizer import draw_fire_detections, fire_label


class FireVisualizerTests(unittest.TestCase):
    def test_fire_labels_identify_candidate_stable_and_temporal_hold(self):
        detection = {"class_name": "fire", "confidence": 0.31}
        self.assertEqual(fire_label(detection), "FIRE CANDIDATE")
        self.assertEqual(fire_label(detection, stable_fire=True), "FIRE")
        self.assertEqual(fire_label({**detection, "temporal_hold": True}, stable_fire=True), "FIRE HOLD")

    def test_smoke_is_not_labeled_or_drawn(self):
        image = np.zeros((80, 80, 3), dtype=np.uint8)
        draw_fire_detections(image, [{"class_name": "smoke", "confidence": 0.9, "bbox": [10, 10, 40, 40]}])
        self.assertEqual(fire_label({"class_name": "smoke"}), "")
        self.assertFalse(image.any())


if __name__ == "__main__":
    unittest.main()