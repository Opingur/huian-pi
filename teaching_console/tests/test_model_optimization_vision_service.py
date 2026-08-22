from __future__ import annotations

import unittest

from teaching_console.services.model_optimization_vision_service import DifficultFrame, select_difficult_frames


class DifficultFrameSelectionTests(unittest.TestCase):
    def test_limit_is_never_more_than_twenty_five(self) -> None:
        candidates = [DifficultFrame(index * 50, float(index), 1, None, None, ("x",), float(index)) for index in range(60)]
        self.assertEqual(25, len(select_difficult_frames(candidates, 99, 1)))

    def test_nearby_times_are_deduplicated(self) -> None:
        candidates = [
            DifficultFrame(100, 1.0, 4, .4, .2, ("x",), 10),
            DifficultFrame(103, 1.1, 4, .4, .2, ("x",), 9),
            DifficultFrame(120, 2.0, 4, .4, .2, ("x",), 8),
        ]
        selected = select_difficult_frames(candidates, 5, 10)
        self.assertEqual([100, 120], [item.frame_index for item in selected])


if __name__ == "__main__":
    unittest.main()
