from __future__ import annotations

import unittest
import sqlite3

from teaching_console.services.research_prediction_workflow import (
    select_frozen_prediction_anchor,
    validation_cards,
)


def anchor(time_seconds: float = 15.0) -> dict[str, object]:
    return {
        "anchor_time_seconds": time_seconds,
        "prediction_10": 12.0,
        "prediction_20": 15.0,
        "prediction_30": 18.0,
        "prediction_horizons": "[10, 20, 30]",
    }


class PredictionWorkflowTests(unittest.TestCase):
    def test_normal_video_exposes_all_real_future_targets(self) -> None:
        cards = validation_cards(anchor(), fps=15, video_duration_seconds=50)
        self.assertEqual([(card["target_time_seconds"], card["frame_index"]) for card in cards], [(25.0, 375), (35.0, 525), (45.0, 675)])
        self.assertTrue(all(card["available"] for card in cards))

    def test_short_video_marks_only_out_of_range_target_unavailable(self) -> None:
        cards = validation_cards(anchor(), fps=15, video_duration_seconds=40)
        self.assertEqual([card["available"] for card in cards], [True, True, False])
        self.assertEqual(cards[-1]["target_time_seconds"], 45.0)

    def test_selected_time_requires_nearby_frozen_prediction(self) -> None:
        rows = [anchor(8.0), anchor(15.0)]
        self.assertEqual(select_frozen_prediction_anchor(rows, selected_time_seconds=15.3, video_duration_seconds=50)["anchor_time_seconds"], 15.0)
        self.assertIsNone(select_frozen_prediction_anchor(rows, selected_time_seconds=12.0, video_duration_seconds=50))
        self.assertIsNone(select_frozen_prediction_anchor([], selected_time_seconds=15.0, video_duration_seconds=50))

    def test_sqlite_rows_are_supported_without_recomputing_predictions(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute("CREATE TABLE predictions (anchor_time_seconds REAL, prediction_10 REAL, prediction_20 REAL, prediction_30 REAL, prediction_horizons TEXT)")
        connection.execute("INSERT INTO predictions VALUES (15, 12, 15, 18, '[10, 20, 30]')")
        row = connection.execute("SELECT * FROM predictions").fetchone()
        self.assertTrue(all(card["available"] for card in validation_cards(row, fps=15, video_duration_seconds=50)))
        connection.close()


if __name__ == "__main__":
    unittest.main()
