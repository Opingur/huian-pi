from __future__ import annotations

import unittest

from teaching_console.services.trend_crowd_teaching_service import (
    calculate_nice_y_axis,
    calculate_x_ticks,
    normalize_observed_second,
    split_continuous_segments,
    update_observed_history,
)


class ObservedHistoryTests(unittest.TestCase):
    def test_absolute_seconds_are_normalized_and_overwritten(self) -> None:
        observed: dict[int, int] = {}
        self.assertEqual(normalize_observed_second(1.02), 1)
        self.assertEqual(normalize_observed_second(1.98), 2)
        update_observed_history(observed, 5.02, 9)
        update_observed_history(observed, 4.98, 10)
        self.assertEqual(observed, {5: 10})

    def test_gaps_split_and_later_observations_merge_segments(self) -> None:
        observed: dict[int, int] = {}
        for second in range(6):
            update_observed_history(observed, second, second + 1)
        for second in (10, 11, 12):
            update_observed_history(observed, second, second + 1)
        self.assertEqual(tuple(tuple(second for second, _people in segment) for segment in split_continuous_segments(observed)), ((0, 1, 2, 3, 4, 5), (10, 11, 12)))
        for second in (6, 7, 8):
            update_observed_history(observed, second, second + 1)
        self.assertEqual(tuple(tuple(second for second, _people in segment) for segment in split_continuous_segments(observed)), ((0, 1, 2, 3, 4, 5, 6, 7, 8), (10, 11, 12)))
        update_observed_history(observed, 9, 10)
        self.assertEqual(tuple(tuple(second for second, _people in segment) for segment in split_continuous_segments(observed)), (tuple(range(13)),))

    def test_empty_and_single_observation_are_safe(self) -> None:
        self.assertEqual(split_continuous_segments({}), ())
        self.assertEqual(split_continuous_segments({7: 3}), (((7, 3),),))
        self.assertEqual(calculate_x_ticks(0), (0,))
        self.assertEqual(calculate_x_ticks(12), tuple(range(13)))

    def test_nice_y_axes_are_zero_based_integer_ticks_with_headroom(self) -> None:
        self.assertEqual(calculate_nice_y_axis(5), (6, 1, (0, 1, 2, 3, 4, 5, 6)))
        self.assertEqual(calculate_nice_y_axis(9), (10, 2, (0, 2, 4, 6, 8, 10)))
        self.assertEqual(calculate_nice_y_axis(14), (16, 2, (0, 2, 4, 6, 8, 10, 12, 14, 16)))
        self.assertEqual(calculate_nice_y_axis(30), (35, 5, (0, 5, 10, 15, 20, 25, 30, 35)))


if __name__ == "__main__":
    unittest.main()
