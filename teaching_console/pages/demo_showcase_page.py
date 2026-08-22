"""Pi-owned showcase controls; Windows only sends explicit HTTP demo commands."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from teaching_console.services.teacher_remote_service import TeacherRemoteClient, TeacherRemoteError, TeacherRemoteSettings, TeacherRemoteSettingsStore, demo_case_row


def demo_state_text(state: dict[str, object]) -> str:
    return f"状态：{state.get('state', '—')}　案例：{state.get('case_id') or '—'}　时间：{float(state.get('position_seconds', 0.0) or 0.0):.1f} s"


class DemoShowcasePage(ttk.Frame):
    def __init__(self, master, project_root) -> None:
        super().__init__(master, padding=12)
        self.store = TeacherRemoteSettingsStore(project_root)
        self.address_var = tk.StringVar(value=self.store.load().base_url)
        self.connection_var = tk.StringVar(value="○ 树莓派未连接")
        self.state_var = tk.StringVar(value="状态：—")
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._polling = self._inflight = self._closed = False
        self._dashboard_photo = None
        self._build(); self.after(50, self._drain_events)

    def _build(self) -> None:
        ttk.Label(self, text="展示演示", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(self, text="案例、时间轴、正式 Dashboard 画面和 ESP32 UART 均由树莓派统一管理；Windows 不直接控制 ESP32。", wraplength=1000).pack(anchor="w", pady=(3, 8))
        link = ttk.LabelFrame(self, text="树莓派连接", padding=8); link.pack(fill="x")
        ttk.Entry(link, textvariable=self.address_var, width=42).pack(side="left")
        ttk.Button(link, text="保存并连接", command=self.connect).pack(side="left", padx=4)
        ttk.Button(link, text="刷新案例", command=self.refresh).pack(side="left")
        ttk.Label(link, textvariable=self.connection_var).pack(side="right")
        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True, pady=(10, 0))
        left = ttk.LabelFrame(body, text="树莓派演示案例", padding=8); right = ttk.LabelFrame(body, text="正式 Dashboard 演示画面", padding=8)
        body.add(left, weight=1); body.add(right, weight=3)
        self.tree = ttk.Treeview(left, columns=("title", "duration"), show="headings", height=14)
        self.tree.heading("title", text="案例"); self.tree.heading("duration", text="时长")
        self.tree.column("title", width=180); self.tree.column("duration", width=75, anchor="e")
        self.tree.pack(fill="both", expand=True)
        self.image_label = ttk.Label(right, text="连接后显示树莓派播放的正式 Dashboard 画面。", anchor="center")
        self.image_label.pack(fill="both", expand=True)
        controls = ttk.Frame(self); controls.pack(fill="x", pady=8)
        for label, action in (("开始", "start"), ("暂停", "pause"), ("继续", "resume"), ("重新开始", "restart"), ("停止", "stop")):
            ttk.Button(controls, text=label, command=lambda value=action: self.command(value)).pack(side="left", padx=(0, 6))
        ttk.Label(controls, textvariable=self.state_var).pack(side="right")

    def connect(self) -> None:
        settings = TeacherRemoteSettings(self.address_var.get()); self.store.save(settings); self.address_var.set(settings.base_url)
        self._polling = True; self.refresh()

    def command(self, action: str) -> None:
        case_id = self.tree.selection()[0] if self.tree.selection() else None
        if action == "start" and not case_id:
            messagebox.showinfo("请选择案例", "请先从树莓派案例列表选择一个案例。", parent=self); return
        self._request(action, case_id)

    def refresh(self) -> None: self._request("refresh", None)

    def _request(self, action: str, case_id: str | None) -> None:
        if self._closed or self._inflight: return
        self._inflight = True; address = self.address_var.get()
        def work() -> None:
            try:
                client = TeacherRemoteClient(address)
                health = client.health()
                if action == "refresh": result = None
                else: result = client.demo_command(action, case_id=case_id)
                cases, state = client.cases(), client.demo_state()
                try: frame = client.frame()
                except TeacherRemoteError: frame = None
                self._events.put(("ok", (health, cases, state if result is None else result, frame)))
            except TeacherRemoteError as error: self._events.put(("error", str(error)))
        threading.Thread(target=work, name="huian-demo-http", daemon=True).start()

    def _drain_events(self) -> None:
        if self._closed: return
        while True:
            try: kind, payload = self._events.get_nowait()
            except queue.Empty: break
            self._inflight = False
            if kind == "error": self.connection_var.set("○ 树莓派未连接：" + str(payload)); continue
            health, cases, state, frame = payload
            self.connection_var.set("● 树莓派已连接：" + str(health.get("hostname", "huian-pi")))
            selected = self.tree.selection()[0] if self.tree.selection() else ""
            self.tree.delete(*self.tree.get_children())
            for case in cases:
                case_id, title, duration = demo_case_row(case); self.tree.insert("", "end", iid=case_id, values=(title or case_id, duration))
            if selected and self.tree.exists(selected): self.tree.selection_set(selected)
            self.state_var.set(demo_state_text(state))
            if frame:
                try:
                    image = Image.open(__import__("io").BytesIO(frame)); image.thumbnail((780, 540)); self._dashboard_photo = ImageTk.PhotoImage(image)
                    self.image_label.configure(image=self._dashboard_photo, text="")
                except Exception: self.image_label.configure(image="", text="树莓派画面格式无效。")
        if self._polling: self.after(250, self.refresh)
        self.after(50, self._drain_events)

    def on_show(self) -> None:
        if self._polling: self.refresh()
    def on_hide(self) -> None: self._polling = False
    def close(self) -> None: self._closed, self._polling = True, False