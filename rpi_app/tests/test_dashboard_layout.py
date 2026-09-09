import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

from ui.dashboard_layout import CANVAS_HEIGHT, CANVAS_WIDTH, STATUS_Y, VIDEO_HEIGHT, VIDEO_WIDTH, _draw_flow_card, _draw_live_trend, _environment_rows, _summary, _top_fire_text, draw_dashboard


class DashboardLayoutTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.full((720, 1280, 3), (32, 64, 96), dtype=np.uint8)
        self.status = {
            "vision_risk": "NORMAL", "visual_alarm": "NONE", "fire_confirmed": False,
            "fire_detected_raw": False, "smoke_detected_raw": False,
            "vision_fire_suspected": False, "vision_smoke_suspected": False,
            "recent_fire_evidence": False,
            "total_people": 0, "tracked_people": 0, "moving_people": 0,
            "prediction_valid": False, "crowd_index": 0.0,
        }
        self.context = {
            "prediction_history": [], "flow_groups": {}, "motions": {},
            "frame_width": 1280, "frame_height": 720, "fire_detections": [],
            "esp32_status": None, "esp32_status_stale": True, "esp32_configured": False,
        }

    def _render(self, status=None, context=None, mode="live"):
        merged_status = {**self.status, **(status or {})}
        merged_context = {**self.context, **(context or {})}
        return draw_dashboard(self.frame, [], merged_status, display={"mode": mode}, ui_context=merged_context)

    def test_lightweight_title_overlay_keeps_main_image_uncovered(self):
        image = self._render()
        self.assertEqual(image.shape, (CANVAS_HEIGHT, CANVAS_WIDTH, 3))
        self.assertEqual(VIDEO_WIDTH, CANVAS_WIDTH)
        self.assertEqual(image[16, 16].tolist(), self.frame[16, 16].tolist())
        self.assertEqual(image[300, 640].tolist(), self.frame[300, 640].tolist())
        self.assertFalse(np.all(image[STATUS_Y + 20, 640] == 255))

    def test_no_people_without_fire_or_esp32_is_normal_and_explicit(self):
        self.assertEqual(_summary(self.status, self.context), ("综合状态：正常运行", (45, 205, 115)))
        rows = _environment_rows(self.status, self.context)
        self.assertIn(("MQ-2烟雾", "未接入", (165, 180, 197)), rows)
        self.assertIn(("环境温度", "未接入", (165, 180, 197)), rows)
        self.assertIn(("视觉火焰", "未发现", (45, 205, 115)), rows)

    def test_safety_card_keeps_esp32_status_row_without_visual_smoke(self):
        esp32 = SimpleNamespace(system_state="NORMAL", mq2_value=0, mq2_warning=False, temperature_c=30.4, temperature_valid=True, temperature_warning=False)
        rows = _environment_rows(self.status, {**self.context, "esp32_status": esp32, "esp32_status_stale": False, "esp32_configured": True})
        labels = [label for label, _value, _color in rows]
        self.assertEqual(labels, ["\u89c6\u89c9\u706b\u7130", "MQ-2\u70df\u96fe", "\u73af\u5883\u6e29\u5ea6", "ESP32\u72b6\u6001", "\u591a\u6e90\u72b6\u6001"])
        self.assertNotIn("\u89c6\u89c9\u70df\u96fe", labels)
        self.assertIn(("ESP32\u72b6\u6001", "\u5728\u7ebf / \u6b63\u5e38", (45, 205, 115)), rows)

    def test_crowd_warning_is_blue_and_confirmed_crowd_is_yellow(self):
        self.assertEqual(_summary({**self.status, "vision_risk": "WARNING"}, self.context), ("综合状态：拥挤预警", (55, 150, 255)))
        self.assertEqual(_summary({**self.status, "vision_risk": "CROWD"}, self.context), ("综合状态：拥挤报警", (255, 210, 60)))

    def test_single_raw_candidate_is_hidden_from_the_public_dashboard(self):
        status = {**self.status, "fire_detected_raw": True, "fire_candidate_visible": False}
        self.assertEqual(_summary(status, self.context), ("综合状态：正常运行", (45, 205, 115)))
        self.assertEqual(_top_fire_text(status, self.context)[0], "视觉火情：未发现")

    def test_same_position_candidate_can_be_shown_after_temporal_confirmation(self):
        status = {**self.status, "fire_detected_raw": True, "fire_candidate_visible": True}
        self.assertEqual(_summary(status, self.context), ("综合状态：疑似火情", (255, 210, 60)))
        self.assertEqual(_top_fire_text(status, self.context)[0], "视觉火情：疑似火焰")

    def test_visual_smoke_compatibility_fields_do_not_trigger_fire_ui(self):
        smoke_only = {**self.status, "smoke_detected_raw": True, "vision_smoke_suspected": True}
        self.assertEqual(_summary(smoke_only, self.context)[0], "综合状态：正常运行")
        self.assertEqual(_top_fire_text(smoke_only, self.context)[0], "视觉火情：未发现")
    def test_stable_fire_overrides_crowd(self):
        status = {**self.status, "vision_risk": "DANGER", "vision_fire_suspected": True, "recent_fire_evidence": True, "fire_detected_raw": True}
        self.assertEqual(_summary(status, self.context), ("综合状态：视觉火情预警（待多源确认）", (255, 148, 35)))
        self.assertEqual(_top_fire_text(status, self.context)[0], "视觉火情：已发现火焰")

    def test_recent_evidence_without_bbox_is_continuous_observation_not_normal(self):
        status = {**self.status, "recent_fire_evidence": True}
        self.assertEqual(_summary(status, self.context), ("综合状态：视觉火情预警（持续观察）", (255, 148, 35)))
        self.assertEqual(_top_fire_text(status, self.context)[0], "视觉火情：近期发现，持续观察")
        self.assertIn(("视觉火焰", "持续观察", (255, 148, 35)), _environment_rows(status, self.context))

    def test_expired_or_plain_hold_box_cannot_create_a_false_candidate(self):
        held = {"class_name": "fire", "confidence": 0.24, "bbox": [12, 18, 34, 50], "temporal_hold": True}
        self.assertEqual(_summary(self.status, {**self.context, "fire_detections": [held]})[0], "综合状态：正常运行")

    def test_fused_fire_has_highest_priority(self):
        esp32 = SimpleNamespace(system_state="FIRE", mq2_value=235, mq2_warning=True, temperature_c=36.5, temperature_valid=True, temperature_warning=True)
        status = {**self.status, "vision_fire_suspected": True}
        context = {**self.context, "esp32_status": esp32, "esp32_status_stale": False, "esp32_configured": True}
        self.assertEqual(_summary(status, context), ("综合状态：火情报警", (235, 82, 82)))
        self.assertIn(("多源状态", "火情确认", (235, 82, 82)), _environment_rows(status, context))

    def test_mq2_dashboard_line_uses_live_baseline_and_stable_state(self):
        esp32 = SimpleNamespace(
            system_state="NORMAL", mq2_value=147, mq2_warning=False,
            mq2_ready=True, mq2_baseline=144,
            temperature_c=29.2, temperature_valid=True, temperature_warning=False,
        )
        rows = _environment_rows(
            self.status,
            {**self.context, "esp32_status": esp32, "esp32_status_stale": False, "esp32_configured": True},
        )
        self.assertIn(("MQ-2烟雾", "当前 147｜环境基线 144｜状态稳定", (45, 205, 115)), rows)

    def test_mq2_dashboard_line_keeps_preheat_and_warning_clear(self):
        warming = SimpleNamespace(
            system_state="NORMAL", mq2_value=155, mq2_warning=False,
            mq2_ready=False, mq2_baseline=None,
            temperature_c=29.2, temperature_valid=True, temperature_warning=False,
        )
        warning = SimpleNamespace(
            system_state="WARNING", mq2_value=460, mq2_warning=True,
            mq2_ready=True, mq2_baseline=144,
            temperature_c=29.2, temperature_valid=True, temperature_warning=False,
        )
        warm_rows = _environment_rows(
            self.status,
            {**self.context, "esp32_status": warming, "esp32_status_stale": False, "esp32_configured": True},
        )
        warning_rows = _environment_rows(
            self.status,
            {**self.context, "esp32_status": warning, "esp32_status_stale": False, "esp32_configured": True},
        )
        self.assertIn(("MQ-2烟雾", "当前 155｜传感器稳定中", (255, 210, 60)), warm_rows)
        self.assertIn(("MQ-2烟雾", "当前 460｜环境基线 144｜烟雾预警", (55, 150, 255)), warning_rows)

    def test_invalid_temperature_never_becomes_zero_or_none(self):
        esp32 = SimpleNamespace(system_state="NORMAL", mq2_value=0, mq2_warning=False, temperature_c=None, temperature_valid=False, temperature_warning=False)
        rows = _environment_rows(self.status, {**self.context, "esp32_status": esp32, "esp32_status_stale": False, "esp32_configured": True})
        self.assertIn(("环境温度", "数据无效", (255, 210, 60)), rows)

    def test_uncalibrated_trend_uses_live_crowd_index_without_reference_line(self):
        status = {**self.status, "total_people": 8, "prediction_valid": True,
                  "prediction_slope": 1.0, "predicted_people_10s": 18.0,
                  "predicted_people_20s": 28.0, "predicted_people_30s": 38.0,
                  "time_to_warning": 0.0, "time_to_danger": None,
                  "crowd_calibrated": False, "danger_people_threshold": None,
                  "vision_risk": "WARNING"}
        context = {**self.context, "prediction_history": [(0.0, 4, 0), (8.0, 8, 0)],
                   "crowd_calibration": {"calibrated": False, "danger_people_threshold": None}}
        entries, canvas = [], np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH, 3), dtype=np.uint8)
        with patch("ui.dashboard_layout.cv2.line") as line:
            _draw_live_trend(canvas, status, context, entries)
        labels = [entry[1] for entry in entries]
        self.assertIn("实时风险：Crowd Index 判断", labels)
        self.assertIn("当前已进入拥挤预警", labels)
        self.assertNotIn((70, 70, 230), [call.args[3] for call in line.call_args_list if len(call.args) > 3])

    def test_uncalibrated_live_trend_uses_crowd_index_message_not_pending_calibration(self):
        status = {**self.status, "total_people": 11, "vision_risk": "CROWD", "prediction_valid": True,
                  "prediction_slope": 0.5, "predicted_people_10s": 16.0,
                  "predicted_people_20s": 21.0, "predicted_people_30s": 26.0,
                  "time_to_warning": 0.0, "crowd_calibrated": False,
                  "danger_people_threshold": None}
        context = {**self.context, "prediction_history": [(0.0, 7, 0), (8.0, 11, 0)]}
        entries, canvas = [], np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH, 3), dtype=np.uint8)
        _draw_live_trend(canvas, status, context, entries)
        labels = [entry[1] for entry in entries]
        self.assertIn("实时风险：Crowd Index 判断", labels)
        self.assertIn("当前已进入拥挤报警", labels)
        self.assertNotIn("实验危险阈值：待标定", labels)
        self.assertNotIn("需完成真实楼梯实验标定", labels)

    def test_calibrated_trend_uses_explicit_threshold_and_draws_reference_line(self):
        status = {**self.status, "total_people": 8, "prediction_valid": True,
                  "prediction_slope": 1.0, "predicted_people_10s": 18.0,
                  "predicted_people_20s": 28.0, "predicted_people_30s": 38.0,
                  "time_to_danger": 10.0, "crowd_calibrated": True,
                  "danger_people_threshold": 18}
        context = {**self.context, "prediction_history": [(0.0, 4, 0), (8.0, 8, 0)],
                   "crowd_calibration": {"calibrated": True, "danger_people_threshold": 18}}
        entries, canvas = [], np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH, 3), dtype=np.uint8)
        with patch("ui.dashboard_layout.cv2.line") as line:
            _draw_live_trend(canvas, status, context, entries)
        labels = [entry[1] for entry in entries]
        self.assertIn("实验参考阈值：18", labels)
        self.assertIn("预计约 10.0 秒达到实验阈值", labels)
        self.assertIn((70, 70, 230), [call.args[3] for call in line.call_args_list if len(call.args) > 3])

    def test_explain_and_validation_modes_remain_renderable(self):
        self.assertEqual(self._render(mode="explain").shape, (CANVAS_HEIGHT, CANVAS_WIDTH, 3))
        self.assertEqual(self._render(mode="validation").shape, (CANVAS_HEIGHT, CANVAS_WIDTH, 3))
        self.assertEqual(VIDEO_HEIGHT, 740)

    def test_flow_card_keeps_all_text_above_the_orange_status_bar(self):
        entries, canvas = [], np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH, 3), dtype=np.uint8)
        _draw_flow_card(canvas, {**self.status, "total_people": 11, "tracked_people": 11, "moving_people": 5,
                                  "running_count": 0, "crowd_index": 0.34, "running_event": False}, entries)
        self.assertIn("当前事件", [entry[1] for entry in entries])
        self.assertIn("箭头指令", [entry[1] for entry in entries])
        self.assertLess(max(entry[0][1] for entry in entries), STATUS_Y - 12)

    def test_trend_details_stay_inside_the_trend_card_and_below_its_title(self):
        status = {**self.status, "total_people": 1, "prediction_valid": True,
                  "predicted_people_10s": 1.0, "predicted_people_20s": 1.0,
                  "predicted_people_30s": 1.0}
        entries, canvas = [], np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH, 3), dtype=np.uint8)
        _draw_live_trend(canvas, status, {**self.context, "prediction_history": [(0.0, 1, 0)]}, entries)
        risk_entry = next(entry for entry in entries if entry[1] == "实时风险：Crowd Index 判断")
        self.assertEqual(risk_entry[0], (24, 788))

    def test_flow_card_returns_to_compact_two_column_layout(self):
        entries, canvas = [], np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH, 3), dtype=np.uint8)
        _draw_flow_card(canvas, {**self.status, "total_people": 11, "tracked_people": 11, "moving_people": 5,
                                  "running_count": 0, "crowd_index": 0.34, "running_event": False}, entries)
        label_positions = [entry[0][0] for entry in entries if entry[1] in {"当前人数", "跟踪人数", "运动人数", "跑动人数", "拥挤指数", "人流状态", "当前事件", "箭头指令"}]
        self.assertEqual(set(label_positions), {532, 700})

    def test_normal_status_dot_uses_the_same_green_as_the_summary(self):
        image = self._render()
        self.assertEqual(image[STATUS_Y + 38, 34].tolist(), [45, 205, 115])


if __name__ == "__main__":
    unittest.main()
