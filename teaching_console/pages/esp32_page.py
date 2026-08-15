"""ESP32 USB Serial teaching and debugging page."""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, ttk

from teaching_console.services.json_protocol import (
    build_pi_payload, classroom_case, classroom_case_expected_response, encode_uart_message,
    format_json_text, parse_esp32_status, parse_json_object, validate_pi_payload,
)
from teaching_console.services.serial_service import SerialService


class Esp32Page(ttk.Frame):
    def __init__(self, master, connection_changed) -> None:
        super().__init__(master, padding=12)
        self.service = SerialService()
        self.connection_changed = connection_changed
        self.port_var = tk.StringVar()
        self.status_var = tk.StringVar(value="○ 未连接")
        self.protocol_var = tk.StringVar(value="1")
        self.timestamp_var = tk.StringVar(value="0")
        self.risk_var = tk.StringVar(value="NORMAL")
        self.index_var = tk.StringVar(value="0.0")
        self.people_var = tk.StringVar(value="0")
        self.conflict_var = tk.BooleanVar(value=False)
        self.fire_var = tk.BooleanVar(value=False)
        self.fire_confidence_var = tk.StringVar(value="0.0")
        self._build()
        self.refresh_ports()
        self.after(100, self._drain_events)

    def _build(self) -> None:
        ttk.Label(self, text="ESP32 实验", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(self, text="电脑输入的 JSON 模拟树莓派平时发给 ESP32 的视觉结果；点击发送前不会写入串口。", wraplength=960).pack(anchor="w", pady=(2, 8))
        link = ttk.LabelFrame(self, text="USB 串口", padding=8); link.pack(fill="x")
        ttk.Label(link, text="可用串口：").grid(row=0, column=0, sticky="w")
        self.port_box = ttk.Combobox(link, textvariable=self.port_var, width=22, state="readonly")
        self.port_box.grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(link, text="波特率：115200").grid(row=0, column=2, sticky="w", padx=14)
        ttk.Button(link, text="刷新串口", command=self.refresh_ports).grid(row=0, column=3, padx=4)
        ttk.Button(link, text="连接", command=self.connect).grid(row=0, column=4, padx=4)
        ttk.Button(link, text="断开", command=self.disconnect).grid(row=0, column=5, padx=4)
        ttk.Label(link, textvariable=self.status_var).grid(row=0, column=6, sticky="e", padx=16)
        dataflow = ttk.LabelFrame(self, text="教学数据流", padding=8); dataflow.pack(fill="x", pady=(8, 0))
        ttk.Label(dataflow, text="教学台  ↓ USB Serial JSON  ↓ ESP32  ↓ parseVisionJson  ↓ 风险状态机  ↓ RGB / 蜂鸣器\nMQ-2 / DHT11  ↓ ESP32  ↓ USB Serial esp32_status JSON  ↓ 教学台", justify="left").pack(anchor="w")
        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True, pady=(8, 0))
        simple, editor = ttk.Frame(body), ttk.Frame(body)
        body.add(simple, weight=1); body.add(editor, weight=2)
        self._build_simple(simple)
        self._build_editor(editor)
        logs = ttk.LabelFrame(self, text="原始串口日志", padding=6); logs.pack(fill="both", expand=True, pady=(8, 0))
        self.log = tk.Text(logs, height=10, wrap="word", state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)
        ttk.Button(logs, text="清空日志", command=self._clear_log).pack(anchor="e", pady=(5, 0))

    def _build_simple(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="简单模式：正式 Pi payload", padding=8); box.pack(fill="both", expand=True, padx=(0, 6))
        fields = (("protocol_version", self.protocol_var), ("timestamp", self.timestamp_var), ("vision_risk", self.risk_var), ("crowd_index", self.index_var), ("total_people", self.people_var), ("vision_fire_confidence", self.fire_confidence_var))
        for row, (name, variable) in enumerate(fields):
            ttk.Label(box, text=name).grid(row=row, column=0, sticky="w", pady=2)
            if name == "vision_risk":
                ttk.Combobox(box, textvariable=variable, values=("NORMAL", "WARNING", "CROWD", "DANGER"), state="readonly", width=14).grid(row=row, column=1, sticky="ew", pady=2)
            else:
                ttk.Entry(box, textvariable=variable, width=16).grid(row=row, column=1, sticky="ew", pady=2)
        ttk.Checkbutton(box, text="direction_conflict", variable=self.conflict_var).grid(row=6, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(box, text="vision_fire_suspected", variable=self.fire_var).grid(row=7, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(box, text="视觉 smoke 字段按当前 Pi 正式协议固定 false / 0.0。", wraplength=250).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 2))
        ttk.Button(box, text="生成 JSON", command=self.generate_json).grid(row=9, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Separator(box).grid(row=10, column=0, columnspan=2, sticky="ew", pady=12)
        ttk.Label(box, text="预制课堂案例（只加载，不发送）").grid(row=11, column=0, columnspan=2, sticky="w")
        for index, label in enumerate(("NORMAL", "WARNING", "CROWD", "DANGER", "PROTOCOL_ERROR", "INVALID_JSON")):
            ttk.Button(box, text={"PROTOCOL_ERROR": "协议错误示例", "INVALID_JSON": "非法 JSON 示例"}.get(label, label + " 示例"), command=lambda value=label: self._load_case(value)).grid(row=12 + index, column=0, columnspan=2, sticky="ew", pady=2)
        box.columnconfigure(1, weight=1)

    def _build_editor(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="高级 JSON 编辑器", padding=8); box.pack(fill="both", expand=True, padx=(6, 0))
        self.editor = tk.Text(box, height=23, wrap="none", font=("Consolas", 10))
        self.editor.pack(fill="both", expand=True)
        buttons = ttk.Frame(box); buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="格式化 JSON", command=self.format_json).pack(side="left")
        ttk.Button(buttons, text="检查 JSON", command=self.check_json).pack(side="left", padx=6)
        ttk.Button(buttons, text="发送到 ESP32", command=self.send).pack(side="left")
        ttk.Button(buttons, text="清空", command=lambda: self._set_text("")).pack(side="left", padx=6)
        self.result_var = tk.StringVar(value="等待输入。")
        ttk.Label(box, textvariable=self.result_var, wraplength=520).pack(anchor="w", pady=(7, 0))
        status = ttk.LabelFrame(box, text="ESP32 回传解析状态", padding=6); status.pack(fill="x", pady=(8, 0))
        self.esp32_status = tk.StringVar(value="尚未收到合法 esp32_status JSON。")
        ttk.Label(status, textvariable=self.esp32_status, justify="left", wraplength=520).pack(anchor="w")

    def generate_json(self) -> None:
        try:
            payload = build_pi_payload({"protocol_version": self.protocol_var.get(), "timestamp": self.timestamp_var.get(), "vision_risk": self.risk_var.get(), "crowd_index": self.index_var.get(), "total_people": self.people_var.get(), "direction_conflict": self.conflict_var.get(), "vision_fire_suspected": self.fire_var.get(), "vision_fire_confidence": self.fire_confidence_var.get()})
        except (TypeError, ValueError) as error:
            messagebox.showerror("输入错误", f"简单模式数值无效：{error}", parent=self); return
        self._set_text(__import__("json").dumps(payload, ensure_ascii=False, indent=2))
        self.result_var.set("已生成完整正式 Pi payload；尚未发送。")

    def _load_case(self, name: str) -> None:
        self._set_text(classroom_case(name))
        self.result_var.set("案例已加载；请检查后主动点击发送。" + classroom_case_expected_response(name))

    def format_json(self) -> None:
        try:
            self._set_text(format_json_text(self._text())); self.result_var.set("JSON 格式化完成。")
        except (ValueError, TypeError, __import__("json").JSONDecodeError) as error:
            self.result_var.set(f"JSON 格式错误：{error}")

    def check_json(self) -> None:
        try:
            payload = parse_json_object(self._text()); valid, note = validate_pi_payload(payload)
            self.result_var.set(("检查通过：" if valid else "JSON 有效，但 ") + note)
        except (ValueError, TypeError, __import__("json").JSONDecodeError) as error:
            self.result_var.set(f"JSON 格式错误：{error}")

    def send(self) -> None:
        try:
            encoded = encode_uart_message(self._text())
        except (ValueError, TypeError, __import__("json").JSONDecodeError) as error:
            messagebox.showerror("不能发送", f"JSON 格式错误：{error}", parent=self); return
        try:
            self.service.send(encoded)
        except RuntimeError as error:
            messagebox.showerror("不能发送", str(error), parent=self); self._set_connection(False); return
        self.result_var.set("已按 UTF-8 单行 JSON + 换行发送。")

    def refresh_ports(self) -> None:
        ports = self.service.list_ports(); self.port_box["values"] = ports
        if ports and self.port_var.get() not in ports: self.port_var.set(ports[0])
        self.result_var.set("已刷新串口。" if ports else "未发现可用串口；请连接 ESP32 后刷新。")

    def connect(self) -> None:
        if not self.port_var.get():
            messagebox.showwarning("请选择串口", "请先选择一个 COM 口。", parent=self); return
        try:
            self.service.connect(self.port_var.get(), 115200)
        except RuntimeError as error:
            messagebox.showerror("连接失败", str(error), parent=self); return
        self._set_connection(True)

    def disconnect(self) -> None:
        self.service.disconnect(); self._set_connection(False)

    def _set_connection(self, connected: bool) -> None:
        self.status_var.set("● 已连接" if connected else "○ 未连接")
        self.connection_changed(connected, self.service.port if connected else "", 115200)

    def _drain_events(self) -> None:
        while True:
            try: event = self.service.events.get_nowait()
            except queue.Empty: break
            self._append_log(f"{event.timestamp} {event.direction:<6} {event.text}")
            if event.direction == "RX":
                parsed = parse_esp32_status(event.text)
                if parsed is not None:
                    temp = parsed["temperature_c"] if parsed["temperature_valid"] else "无有效读数"
                    humidity = parsed.get("humidity_percent", "未提供")
                    self.esp32_status.set(f"MQ-2 ADC：{parsed['mq2_value']}\nMQ-2 warning：{parsed['mq2_warning']}\n温度：{temp}\n温度有效：{parsed['temperature_valid']}\n温度预警：{parsed['temperature_warning']}\n系统状态：{parsed['system_state']}\n视觉有效：{parsed['vision_valid']}\n湿度：{humidity}")
            if event.direction == "SYSTEM" and "断开" in event.text: self._set_connection(False)
        self.after(100, self._drain_events)

    def _text(self) -> str: return self.editor.get("1.0", "end-1c")
    def _set_text(self, text: str) -> None: self.editor.delete("1.0", "end"); self.editor.insert("1.0", text)
    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal"); self.log.insert("end", text + "\n"); self.log.see("end"); self.log.configure(state="disabled")
    def _clear_log(self) -> None: self.log.configure(state="normal"); self.log.delete("1.0", "end"); self.log.configure(state="disabled")
    def close(self) -> None: self.service.close()
