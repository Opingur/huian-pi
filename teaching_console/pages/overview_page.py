"""Read-only system overview page."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class OverviewPage(ttk.Frame):
    def __init__(self, master, project_root) -> None:
        super().__init__(master, padding=16)
        ttk.Label(self, text="系统总览", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(self, text="以下为当前仓库已实现的数据流。教学台只说明和调试，不替代视觉主程序。", wraplength=900).pack(anchor="w", pady=(4, 14))
        modules = (
            ("IMX219 摄像头", "输入", "Picamera2 实时 BGR 帧", "rpi_app/sources/picamera_source.py"),
            ("YOLO 人员检测 + ByteTrack 目标跟踪", "视频 / 摄像头主链", "PersonTracker.track 内部调用 Ultralytics model.track；仅 person (class 0)。", "rpi_app/vision/tracker.py"),
            ("轨迹与运动方向", "连续画面轨迹", "Track ID、底部中心轨迹、heading_angle、画面相对速度。", "rpi_app/vision/trajectory.py"),
            ("人流分析 / 空间汇合", "流组质心相对运动", "convergence_score、风险、ETA、汇合点；Conflict Zone 不是正式评分直接输入。", "rpi_app/decision/flow_analysis.py"),
            ("人数历史 / 短时趋势", "固定左右区域占用", "30 秒历史；最近 15 秒回归；10/20/30 秒人数预测。", "rpi_app/vision/people_flow.py\nrpi_app/decision/crowd_predictor.py"),
            ("Crowd Index / 视觉风险", "密度、增长、空间汇合", "density + growth + convergence，当前权重 0.5 / 0.3 / 0.2。", "rpi_app/decision/crowd_index.py"),
            ("UART JSON", "视觉 status", "Pi 正式 10 字段 JSON，一行一条、UTF-8。", "rpi_app/communication/esp32.py"),
            ("ESP32", "Pi UART2 或课堂 USB", "parseVisionJson → 风险状态机 → RGB/蜂鸣器；并回传 esp32_status。", "esp32_firmware/huian_esp32/huian_esp32.ino"),
            ("MQ-2 / DHT11", "ESP32 本地传感器", "mq2_value、温度与系统状态回传。", "esp32_firmware/huian_esp32/huian_esp32.ino"),
        )
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        for index, (title, kind, detail, path) in enumerate(modules):
            card = ttk.LabelFrame(body, text=f"{index + 1}. {title}", padding=10)
            card.pack(fill="x", pady=4)
            ttk.Label(card, text=f"作用：{kind}", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
            ttk.Label(card, text=detail, wraplength=850).grid(row=1, column=0, sticky="w", pady=2)
            ttk.Label(card, text=f"真实源码：{path}", foreground="#444444").grid(row=2, column=0, sticky="w")
        ttk.Separator(self).pack(fill="x", pady=10)
        ttk.Label(self, text="图片模式例外：rpi_app/vision/detector.py 的 PersonDetector 是单帧旧链，不是视频 / 摄像头模式中 PersonTracker 之前的一个步骤。", wraplength=950).pack(anchor="w")
        ttk.Label(self, text="预测例外：未完成 crowd calibration，danger_people_threshold 为 null，因此当前 time_to_danger 不显示倒计时。", wraplength=950).pack(anchor="w", pady=(4, 0))
        ttk.Label(self, text="成品状态语义：NORMAL=绿灯静音；WARNING=蓝灯慢速短鸣；CROWD=黄闪快速短鸣；DANGER=火警红闪持续长鸣。内部 FIRE 仍是独立确认火情来源。", wraplength=950).pack(anchor="w", pady=(4, 0))
