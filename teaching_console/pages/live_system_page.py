"""Teacher view of the formal Pi dashboard without blocking Tkinter."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from teaching_console.services.teacher_remote_service import (
    TeacherRemoteClient, TeacherRemoteError, TeacherRemoteSettings, TeacherRemoteSettingsStore, live_status_rows,
)


class LiveSystemPage(ttk.Frame):
    def __init__(self, master, project_root) -> None:
        super().__init__(master, padding=12)
        self.store = TeacherRemoteSettingsStore(project_root)
        self.address_var = tk.StringVar(value=self.store.load().base_url)
        self.connection_var = tk.StringVar(value="○ 树莓派未连接")
        self.fields = {label: tk.StringVar(value="—") for label, _ in live_status_rows({})}
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._polling = False
        self._inflight = False
        self._closed = False
        self._dashboard_photo = None
        self._build()
        self.after(50, self._drain_events)

    def _build(self) -> None:
        ttk.Label(self, text="实时系统", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(self, text="通过 Wi-Fi 查看树莓派正式 Dashboard 和同一份正式状态；本页不重新推理，也不连接 Windows USB ESP32。", wraplength=1000).pack(anchor="w", pady=(3, 8))
        connection = ttk.LabelFrame(self, text="树莓派连接", padding=8); connection.pack(fill="x")
        ttk.Label(connection, text="地址：").pack(side="left")
        ttk.Entry(connection, textvariable=self.address_var, width=42).pack(side="left", padx=4)
        ttk.Button(connection, text="保存并连接", command=self.connect).pack(side="left", padx=4)
        ttk.Button(connection, text="刷新", command=self.refresh).pack(side="left")
        ttk.Label(connection, textvariable=self.connection_var).pack(side="right")
        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True, pady=(10, 0))
        viewer = ttk.LabelFrame(body, text="树莓派正式 Dashboard 当前画面", padding=8)
        details = ttk.LabelFrame(body, text="必要运行状态", padding=10)
        body.add(viewer, weight=4); body.add(details, weight=1)
        self.image_label = ttk.Label(viewer, text="连接树莓派后显示最新正式 Dashboard JPEG。", anchor="center")
        self.image_label.pack(fill="both", expand=True)
        for index, (label, _value) in enumerate(live_status_rows({})):
            ttk.Label(details, text=label).grid(row=index, column=0, sticky="w", pady=5)
            ttk.Label(details, textvariable=self.fields[label], wraplength=210).grid(row=index, column=1, sticky="e", pady=5, padx=(10, 0))
        details.columnconfigure(1, weight=1)

    def connect(self) -> None:
        settings = TeacherRemoteSettings(self.address_var.get())
        self.store.save(settings)
        self.address_var.set(settings.base_url)
        self._polling = True
        self.connection_var.set("○ 正在连接树莓派…")
        self.refresh()

    def refresh(self) -> None:
        if self._closed or self._inflight:
            return
        self._inflight = True
        address = self.address_var.get()
        def work() -> None:
            try:
                client = TeacherRemoteClient(address)
                health, status = client.health(), client.status()
                try: frame = client.frame()
                except TeacherRemoteError: frame = None
                self._events.put(("ok", (health, status, frame)))
            except TeacherRemoteError as error:
                self._events.put(("error", str(error)))
        threading.Thread(target=work, name="huian-live-http", daemon=True).start()

    def _drain_events(self) -> None:
        if self._closed:
            return
        while True:
            try: kind, payload = self._events.get_nowait()
            except queue.Empty: break
            self._inflight = False
            if kind == "error":
                self.connection_var.set("○ 树莓派未连接：" + str(payload))
                continue
            health, status, frame = payload
            self.connection_var.set("● 树莓派已连接：" + str(health.get("hostname", "huian-pi")))
            for label, value in live_status_rows(status): self.fields[label].set(value)
            if frame:
                try:
                    image = Image.open(__import__("io").BytesIO(frame)); image.thumbnail((780, 560))
                    self._dashboard_photo = ImageTk.PhotoImage(image)
                    self.image_label.configure(image=self._dashboard_photo, text="")
                except Exception:
                    self.image_label.configure(text="树莓派画面格式无效。", image="")
        if self._polling:
            self.after(250, self.refresh)
        self.after(50, self._drain_events)

    def on_show(self) -> None:
        if self._polling: self.refresh()
    def on_hide(self) -> None: self._polling = False
    def close(self) -> None: self._closed, self._polling = True, False