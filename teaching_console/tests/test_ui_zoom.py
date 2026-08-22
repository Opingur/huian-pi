from __future__ import annotations

import unittest

from teaching_console.ui_zoom import ZoomManager, scaled_value


class _Event:
    def __init__(self, delta: int, state: int = 0) -> None:
        self.delta = delta
        self.state = state


class _Page:
    def __init__(self) -> None:
        self.factors: list[float] = []
        self.tracker_resets = 0
        self.predictor_resets = 0
        self.observed_history = [(0, 2), (1, 3)]
        self.ground_truth = {"annotation-1": 4}

    def on_zoom_changed(self, factor: float) -> None:
        self.factors.append(factor)


class ZoomManagerTests(unittest.TestCase):
    def test_default_and_steps(self) -> None:
        zoom = ZoomManager()
        self.assertEqual(100, zoom.zoom_percent)
        self.assertEqual(110, zoom.zoom_in())
        self.assertEqual(100, zoom.zoom_out())

    def test_limits_and_reset(self) -> None:
        zoom = ZoomManager()
        self.assertEqual(160, zoom.set_zoom(999))
        self.assertEqual(70, zoom.set_zoom(-1))
        zoom.set_zoom(130)
        self.assertEqual(100, zoom.reset_zoom())

    def test_base_values_do_not_accumulate_rounding(self) -> None:
        zoom = ZoomManager()
        zoom.zoom_in()
        self.assertEqual(704, scaled_value(640, zoom.get_zoom_factor()))
        zoom.set_zoom(120)
        self.assertEqual(768, scaled_value(640, zoom.get_zoom_factor()))
        self.assertEqual(504, scaled_value(420, zoom.get_zoom_factor()))

    def test_callback_receives_current_factor_without_resetting_page_state(self) -> None:
        zoom = ZoomManager()
        page = _Page()
        zoom.add_callback(page.on_zoom_changed)
        history_before = list(page.observed_history)
        ground_truth_before = dict(page.ground_truth)
        zoom.set_zoom(120)
        self.assertEqual([1.2], page.factors)
        self.assertEqual(0, page.tracker_resets)
        self.assertEqual(0, page.predictor_resets)
        self.assertEqual(history_before, page.observed_history)
        self.assertEqual(ground_truth_before, page.ground_truth)

    def test_plain_wheel_does_not_zoom_but_ctrl_wheel_does(self) -> None:
        zoom = ZoomManager()
        self.assertIsNone(zoom.handle_ctrl_mousewheel(_Event(120)))
        self.assertEqual(100, zoom.zoom_percent)
        self.assertEqual("break", zoom.handle_ctrl_mousewheel(_Event(120, state=0x0004)))
        self.assertEqual(110, zoom.zoom_percent)

    def test_ctrl_zero_resets(self) -> None:
        zoom = ZoomManager()
        zoom.set_zoom(140)
        self.assertEqual("break", zoom.handle_ctrl_zero())
        self.assertEqual(100, zoom.zoom_percent)


if __name__ == "__main__":
    unittest.main()
