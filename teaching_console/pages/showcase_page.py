"""Default competition presentation surface for the Windows Teaching Console.

The visual pipeline remains local to the child computer.  The Pi is queried only
for a compact status line and, when pre-configured by an adult, receives the
restricted visual-status relay while retaining sole UART ownership.
"""
from __future__ import annotations

import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from teaching_console.services.showcase_bridge_settings import ShowcaseBridgeSettingsStore
from teaching_console.services.showcase_vision_service import (
    ShowcaseEvent, ShowcaseFrame, ShowcaseVisionWorker,
)
from teaching_console.services.teacher_remote_service import (
    TeacherRemoteClient,
    TeacherRemoteError,
    TeacherRemoteSettingsStore,
    showcase_status_text,
)


class ShowcasePage(tk.Frame):
    """A quiet, white exhibition shell around the official Dashboard output."""

    BACKGROUND = "#f6f7f8"
    SURFACE = "#ffffff"
    STAGE = "#edf0f2"
    INK = "#17212b"
    MUTED = "#65727f"
    BORDER = "#d7dde2"
    ACCENT = "#c96b08"

    # These four local project cases are already used by the teaching pipeline.
    # Running and fire are deliberately absent until their final showcase videos
    # are manually accepted; the display must not promote development leftovers.
    CASES = (
        ("000318 · 人数增长", "test_data/iitb_final/000318.mp4"),
        ("000327 · 目标跟踪", "test_data/iitb_final/000327.mp4"),
        ("000345 · 人数下降", "test_data/iitb_final/000345.mp4"),
        ("000353 · 增长趋势", "test_data/iitb_final/000353.mp4"),
    )

    def __init__(self, master, project_root: Path) -> None:
        super().__init__(master, background=self.BACKGROUND, highlightthickness=0)
        self.project_root = Path(project_root)
        self.video_path: Path | None = None
        # A pre-configured environment secret is intentionally invisible to the
        # presenter.  Without it this remains a display-only local analysis.
        stored_bridge_key = ShowcaseBridgeSettingsStore(self.project_root).load().bridge_key
        self.bridge_key = os.environ.get("HUIAN_REMOTE_VISION_KEY", "") or stored_bridge_key
        self.worker = ShowcaseVisionWorker(self.project_root)
        self._photo = None
        self._last_frame: ShowcaseFrame | None = None
        self._running = False
        self._toolbar_visible = False
        self._hide_toolbar_after: str | None = None
        self._pi_events: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=2)
        self._pi_poll_active = False
        self._pi_polling = False
        self._pi_poll_after: str | None = None
        self._case_paths = {
            title: self.project_root / relative for title, relative in self.CASES
            if (self.project_root / relative).is_file()
        }
        self.case_choice = tk.StringVar(value=next(iter(self._case_paths), "选择展示案例"))
        self.pi_status = tk.StringVar(value="树莓派：正在连接")
        self.playback_status = tk.StringVar(value="等待展示案例")
        self._build()
        self.after(40, self._drain_events)

    def _build(self) -> None:
        self.header = tk.Frame(self, background=self.SURFACE, highlightbackground=self.BORDER, highlightthickness=1)
        self.header.pack(side="top", fill="x")
        header = self.header
        tk.Label(
            header, text="慧眼疏流安全检测系统", background=self.SURFACE,
            foreground=self.INK, font=("Segoe UI", 12, "bold"),
        ).pack(side="left", padx=(12, 7), pady=6)
        tk.Label(header, text="展示模式", background=self.SURFACE, foreground=self.MUTED, font=("Segoe UI", 9)).pack(side="left", pady=6)
        tk.Label(
            header, textvariable=self.pi_status, background=self.SURFACE,
            foreground=self.MUTED, font=("Segoe UI", 9),
        ).pack(side="right", padx=12, pady=6)

        self.stage = tk.Frame(self, background=self.STAGE, highlightbackground=self.BORDER, highlightthickness=1)
        self.stage.pack(fill="both", expand=True, padx=6, pady=(6, 3))
        self.image = tk.Label(
            self.stage,
            text="等待展示案例\n\n按 Ctrl+O 选择本地视频，或按 F1 显示展示控制。",
            foreground=self.MUTED, background=self.STAGE, font=("Segoe UI", 12), anchor="center",
        )
        self.image.pack(fill="both", expand=True)
        self.image.bind("<Motion>", self._reveal_toolbar)

        self.footer = tk.Frame(self, background=self.BACKGROUND)
        self.footer.pack(side="bottom", fill="x", padx=8, pady=(0, 3))
        tk.Label(self.footer, textvariable=self.playback_status, background=self.BACKGROUND, foreground=self.MUTED, font=("Segoe UI", 9)).pack(side="right")

        self.toolbar = tk.Frame(self, background=self.SURFACE, highlightbackground=self.BORDER, highlightthickness=1)
        self._add_toolbar_button("案例", self._select_case)
        self._add_toolbar_button("选择视频", self.choose_video)
        self._add_toolbar_button("开始", self.start_or_resume)
        self._add_toolbar_button("暂停", self.toggle_pause)
        self._add_toolbar_button("全屏", self.toggle_fullscreen)
        self._add_toolbar_button("隐藏控制", self._hide_toolbar)
        self.case_picker = ttk.Combobox(
            self.toolbar, textvariable=self.case_choice, values=tuple(self._case_paths), state="readonly", width=20,
        )
        self.case_picker.bind("<<ComboboxSelected>>", self._select_case)
        self.case_picker.pack(side="left", padx=(4, 8), pady=5)
        self.bind_all("<Control-o>", self._choose_shortcut, add="+")
        self.bind_all("<F1>", self._toggle_toolbar_shortcut, add="+")
        self.bind_all("<space>", self._toggle_play_shortcut, add="+")

    def _add_toolbar_button(self, text: str, command) -> None:
        button = tk.Label(
            self.toolbar, text=text, foreground=self.INK, background=self.SURFACE,
            activeforeground=self.ACCENT, activebackground=self.SURFACE,
            cursor="hand2", font=("Segoe UI", 9), padx=8, pady=5, takefocus=True,
        )
        for event in ("<Button-1>", "<Return>"):
            button.bind(event, lambda _event: command())
        button.pack(side="left", padx=(4, 0), pady=1)

    def _place_toolbar(self) -> None:
        self.toolbar.place(relx=0.5, rely=1.0, anchor="s", y=-12)
        self._toolbar_visible = True
        if self._hide_toolbar_after is not None:
            self.after_cancel(self._hide_toolbar_after)
        self._hide_toolbar_after = self.after(4500, self._hide_toolbar)

    def _reveal_toolbar(self, _event=None) -> None:
        if not self._toolbar_visible:
            self._place_toolbar()

    def _hide_toolbar(self, _event=None) -> None:
        self.toolbar.place_forget()
        self._toolbar_visible = False
        self._hide_toolbar_after = None

    def toggle_fullscreen(self) -> None:
        top = self.winfo_toplevel()
        callback = getattr(top, "toggle_showcase_fullscreen", None)
        if callback is not None:
            callback()

    def set_fullscreen(self, enabled: bool) -> None:
        """Hide chrome only in presentation fullscreen; keep the Dashboard ratio."""
        if enabled:
            self.header.pack_forget()
            self.footer.pack_forget()
        else:
            self.header.pack(side="top", fill="x", before=self.stage)
            self.footer.pack(side="bottom", fill="x", padx=8, pady=(0, 3))
        self.after_idle(lambda: self._render_last_frame())

    def _render_last_frame(self) -> None:
        if self._last_frame is not None:
            self._render_frame(self._last_frame)

    def _toggle_toolbar_shortcut(self, _event=None):
        if not self._pi_poll_active:
            return None
        if self._toolbar_visible:
            self._hide_toolbar()
        else:
            self._place_toolbar()
        return "break"

    def _choose_shortcut(self, _event=None):
        if not self._pi_poll_active:
            return None
        self.choose_video()
        return "break"

    def _toggle_play_shortcut(self, _event=None):
        # These global bindings are inert while an experiment page is visible.
        if not self._pi_poll_active:
            return None
        if self.worker.running:
            self.toggle_pause()
        else:
            self.start_or_resume()
        return "break"

    def _select_case(self, _event=None) -> None:
        selected = self._case_paths.get(self.case_choice.get())
        if selected is None:
            return
        self.stop()
        self.video_path = selected
        self.image.configure(image="", text=f"已选择：{selected.name}\n按空格或“开始”播放并进行本机实时分析")
        self.playback_status.set(f"案例：{self.case_choice.get()}")

    def choose_video(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self, title="选择本地展示视频",
            filetypes=[("视频", "*.mp4 *.avi *.mov *.mkv"), ("所有文件", "*.*")],
        )
        if not selected:
            return
        self.stop()
        self.video_path = Path(selected)
        self.case_choice.set("自选视频")
        self.image.configure(image="", text=f"已选择：{self.video_path.name}\n按空格或“开始”播放并进行本机实时分析")
        self.playback_status.set("准备就绪")

    def _bridge_endpoint(self) -> str:
        base = TeacherRemoteSettingsStore(self.project_root).load().base_url
        host = base.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        return f"http://{host}:8781/api/vision"

    def start_or_resume(self) -> None:
        if self.video_path is None:
            self._select_case()
        if self.video_path is None:
            self.choose_video()
        if self.video_path is None:
            return
        if self.worker.running and self.worker.paused:
            self.worker.pause(False)
            self.playback_status.set("继续播放")
            return
        if self.worker.running:
            return
        self.worker.start(self.video_path, bridge_endpoint=self._bridge_endpoint(), bridge_key=self.bridge_key)
        self._running = True
        self.playback_status.set("正在启动本机实时分析…")

    def toggle_pause(self) -> None:
        if not self.worker.running:
            return
        paused = not self.worker.paused
        self.worker.pause(paused)
        self.playback_status.set("已暂停" if paused else "继续播放")

    def _render_frame(self, packet: ShowcaseFrame) -> None:
        self._last_frame = packet
        try:
            frame_rgb = packet.frame_bgr[:, :, ::-1]
            image = Image.fromarray(frame_rgb)
            max_width = max(320, self.stage.winfo_width() - 8)
            max_height = max(240, self.stage.winfo_height() - 8)
            image.thumbnail((max_width, max_height))
            self._photo = ImageTk.PhotoImage(image)
            self.image.configure(image=self._photo, text="")
            total = packet.status.get("total_people", "—")
            risk = packet.status.get("vision_risk", "NORMAL")
            self.playback_status.set(f"{packet.source_time:.1f} s · {total} 人 · {risk}")
        except Exception as error:
            self.playback_status.set("画面显示失败：" + str(error))

    def _fetch_pi_status(self) -> None:
        try:
            settings = TeacherRemoteSettingsStore(self.project_root).load()
            result: tuple[str, object] = ("pi", TeacherRemoteClient(settings.base_url, timeout_seconds=0.8).status())
        except TeacherRemoteError:
            result = ("pi", None)
        try:
            self._pi_events.put_nowait(result)
        except queue.Full:
            try:
                self._pi_events.get_nowait()
            except queue.Empty:
                pass
            self._pi_events.put_nowait(result)
        finally:
            self._pi_polling = False

    def _schedule_pi_poll(self, delay_ms: int = 0) -> None:
        if self._pi_poll_active and self._pi_poll_after is None:
            self._pi_poll_after = self.after(delay_ms, self._poll_pi_status)

    def _poll_pi_status(self) -> None:
        self._pi_poll_after = None
        if not self._pi_poll_active:
            return
        if not self._pi_polling:
            self._pi_polling = True
            threading.Thread(target=self._fetch_pi_status, name="huian-pi-status", daemon=True).start()
        self._schedule_pi_poll(1500)

    def _drain_events(self) -> None:
        while True:
            try:
                event: ShowcaseEvent = self.worker.events.get_nowait()
            except queue.Empty:
                break
            if event.kind == "started":
                data = dict(event.value or {})
                self.playback_status.set("本机实时分析 · 硬件联动已就绪" if data.get("hardware") else "本机实时分析")
            elif event.kind == "frame" and isinstance(event.value, ShowcaseFrame):
                self._render_frame(event.value)
            elif event.kind == "finished":
                if self._running:
                    self.playback_status.set("播放结束")
                self._running = False
            elif event.kind == "error":
                self._running = False
                self.playback_status.set("无法启动")
                messagebox.showerror("现场展示", str(event.value), parent=self)
        while True:
            try:
                kind, value = self._pi_events.get_nowait()
            except queue.Empty:
                break
            if kind == "pi":
                self.pi_status.set(showcase_status_text(value if isinstance(value, dict) else None))
        if self.winfo_exists():
            self.after(40, self._drain_events)

    def on_show(self) -> None:
        self._pi_poll_active = True
        self._schedule_pi_poll()

    def on_hide(self) -> None:
        self._pi_poll_active = False
        if self._pi_poll_after is not None:
            self.after_cancel(self._pi_poll_after)
            self._pi_poll_after = None
        self.stop()
        self._hide_toolbar()

    def stop(self) -> None:
        self.worker.stop()
        self._running = False

    def close(self) -> None:
        self.on_hide()
