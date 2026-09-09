"""Default competition presentation surface for the Windows Teaching Console.

The visual pipeline remains local to the child computer. The Pi is queried only
for a compact status line and, when pre-configured by an adult, receives the
restricted visual-status relay while retaining sole UART ownership.
"""
from __future__ import annotations

import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from teaching_console.services.showcase_bridge_settings import ShowcaseBridgeSettingsStore
from teaching_console.services.showcase_library import ShowcaseVideoEntry, library_entries
from teaching_console.services.showcase_vision_service import (
    ShowcaseEvent, ShowcaseFrame, ShowcaseVisionWorker,
)
from teaching_console.services.teacher_remote_service import (
    TeacherRemoteClient,
    TeacherRemoteError,
    TeacherRemoteSettingsStore,
    showcase_status_text,
)


def format_showcase_time(seconds: float | None) -> str:
    """Format source-video time for non-visual playback status consumers."""
    if seconds is None:
        return "—"
    whole_seconds = max(0, int(seconds))
    return f"{whole_seconds // 60}:{whole_seconds % 60:02d}"


def showcase_image_from_bgr(frame_bgr):
    """Create the Tk source image directly from OpenCV's BGR buffer.

    ``Image.fromarray(frame[:, :, ::-1])`` makes a full RGB copy of every
    Dashboard frame. Pillow can instead decode the already-contiguous BGR
    buffer, eliminating that per-frame NumPy channel-reversal copy.
    """
    height, width = frame_bgr.shape[:2]
    return Image.frombuffer("RGB", (int(width), int(height)), frame_bgr, "raw", "BGR", 0, 1)

class ShowcasePage(tk.Frame):
    """A quiet, white exhibition shell around the official Dashboard output."""

    BACKGROUND = "#f6f7f8"
    SURFACE = "#ffffff"
    STAGE = "#edf0f2"
    INK = "#17212b"
    MUTED = "#65727f"
    BORDER = "#d7dde2"
    ACCENT = "#c96b08"
    UI_POLL_MS = 16

    # Formal project cases appear at the top of the same material list as the
    # curated video library, instead of in a separate selection mode.
    CASES = (
        ("案例② · 跟踪行人", "test_data/iitb_final/000327.mp4"),
        ("案例④ · 人流趋势", "test_data/iitb_final/000353.mp4"),
    )

    def __init__(self, master, project_root: Path) -> None:
        super().__init__(master, background=self.BACKGROUND, highlightthickness=0)
        self.project_root = Path(project_root)
        self.video_path: Path | None = None
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
        self._media_entries: list[ShowcaseVideoEntry] = []
        self._selected_media: ShowcaseVideoEntry | None = None
        self.pi_status = tk.StringVar(value="树莓派：正在连接")
        self.playback_status = tk.StringVar(value="请从右侧素材列表选择视频")
        self.timeline_seconds = tk.DoubleVar(value=0.0)
        self.timeline_text = tk.StringVar(value="0:00 / —")
        self._timeline_duration_seconds: float | None = None
        self._timeline_dragging = False
        self._build()
        self.after(self.UI_POLL_MS, self._drain_events)

    def _build(self) -> None:
        self.header = tk.Frame(
            self, background=self.SURFACE,
            highlightbackground=self.BORDER, highlightthickness=1,
        )
        self.header.pack(side="top", fill="x")
        tk.Label(
            self.header, text="慧眼疏流安全检测系统", background=self.SURFACE,
            foreground=self.INK, font=("Segoe UI", 12, "bold"),
        ).pack(side="left", padx=(12, 7), pady=6)
        tk.Label(
            self.header, text="展示模式", background=self.SURFACE,
            foreground=self.MUTED, font=("Segoe UI", 9),
        ).pack(side="left", pady=6)
        tk.Label(
            self.header, textvariable=self.pi_status, background=self.SURFACE,
            foreground=self.MUTED, font=("Segoe UI", 9),
        ).pack(side="right", padx=12, pady=6)

        self.content = tk.Frame(self, background=self.BACKGROUND)
        self.content.pack(fill="both", expand=True, padx=6, pady=(6, 3))
        self.stage = tk.Frame(
            self.content, background=self.STAGE,
            highlightbackground=self.BORDER, highlightthickness=1,
        )
        self.stage.pack(side="left", fill="both", expand=True)
        self.image = tk.Label(
            self.stage,
            text="等待展示视频\n\n请从右侧“可用素材”列表选择视频。",
            foreground=self.MUTED, background=self.STAGE,
            font=("Segoe UI", 12), anchor="center",
        )
        self.image.pack(fill="both", expand=True)
        self.image.bind("<Button-1>", self._toggle_play_shortcut)
        self._build_media_navigation(self.content)

        self.footer = tk.Frame(self, background=self.BACKGROUND)
        self.footer.pack(side="bottom", fill="x", padx=8, pady=(0, 3))
        timeline_row = tk.Frame(self.footer, background=self.BACKGROUND)
        timeline_row.pack(fill="x", pady=(0, 2))
        self.timeline = ttk.Scale(
            timeline_row, from_=0.0, to=1.0, variable=self.timeline_seconds,
            command=self._on_timeline_motion,
        )
        self.timeline.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.timeline.bind("<ButtonPress-1>", self._begin_timeline_drag)
        self.timeline.bind("<ButtonRelease-1>", self._finish_timeline_drag)
        tk.Label(
            timeline_row, textvariable=self.timeline_text, background=self.BACKGROUND,
            foreground=self.MUTED, font=("Segoe UI", 9), width=12, anchor="e",
        ).pack(side="left")
        tk.Label(
            self.footer, textvariable=self.playback_status,
            background=self.BACKGROUND, foreground=self.MUTED,
            font=("Segoe UI", 9), anchor="e",
        ).pack(fill="x")

        self.toolbar = tk.Frame(
            self, background=self.SURFACE,
            highlightbackground=self.BORDER, highlightthickness=1,
        )
        self._add_toolbar_button("开始", self.start_or_resume)
        self._add_toolbar_button("暂停", self.toggle_pause)
        self._add_toolbar_button("全屏", self.toggle_fullscreen)
        self._add_toolbar_button("隐藏控制", self._hide_toolbar)
        self.bind_all("<F1>", self._toggle_toolbar_shortcut, add="+")
        self.bind_all("<space>", self._toggle_play_shortcut, add="+")
        self._place_toolbar()

    def _update_timeline_text(self) -> None:
        self.timeline_text.set(
            f"{format_showcase_time(self.timeline_seconds.get())} / "
            f"{format_showcase_time(self._timeline_duration_seconds)}"
        )

    def _reset_timeline(self) -> None:
        self._timeline_duration_seconds = None
        self.timeline.configure(to=1.0)
        self.timeline_seconds.set(0.0)
        self._update_timeline_text()

    def _set_timeline_duration(self, duration_seconds: object) -> None:
        duration = (
            float(duration_seconds)
            if isinstance(duration_seconds, (int, float)) and duration_seconds > 0
            else None
        )
        self._timeline_duration_seconds = duration
        self.timeline.configure(to=max(1.0, duration or 1.0))
        self._update_timeline_text()

    def _set_timeline_position(self, source_time: float) -> None:
        if self._timeline_dragging:
            return
        if self._timeline_duration_seconds is not None:
            source_time = min(source_time, self._timeline_duration_seconds)
        self.timeline_seconds.set(max(0.0, source_time))
        self._update_timeline_text()

    def _on_timeline_motion(self, _value=None) -> None:
        if self._timeline_dragging:
            self._update_timeline_text()

    def _begin_timeline_drag(self, _event=None):
        if self.video_path is None:
            return "break"
        self._timeline_dragging = True
        if self.worker.running:
            self.worker.pause(True)
        return None

    def _finish_timeline_drag(self, _event=None):
        if self.video_path is None:
            return "break"
        self._timeline_dragging = False
        target = self.timeline_seconds.get()
        if self._timeline_duration_seconds is not None:
            target = min(target, self._timeline_duration_seconds)
        self._set_timeline_position(target)
        if self.worker.running:
            self.worker.seek(target)
            self.worker.pause(False)
        else:
            self._start_worker(target)
        self.playback_status.set(f"正在跳转到 {format_showcase_time(target)}…")
        return None
    def _add_toolbar_button(self, text: str, command) -> None:
        button = tk.Label(
            self.toolbar, text=text, foreground=self.INK, background=self.SURFACE,
            activeforeground=self.ACCENT, activebackground=self.SURFACE,
            cursor="hand2", font=("Segoe UI", 9), padx=8, pady=5, takefocus=True,
        )
        for event in ("<Button-1>", "<Return>"):
            button.bind(event, lambda _event: command())
        button.pack(side="left", padx=(4, 0), pady=1)

    def _build_media_navigation(self, master) -> None:
        """Restore the material list and place the four formal cases inside it."""
        self.media_sidebar = tk.Frame(
            master, width=330, background=self.SURFACE,
            highlightbackground=self.BORDER, highlightthickness=1,
        )
        self.media_sidebar.pack(side="right", fill="y", padx=(6, 0))
        self.media_sidebar.pack_propagate(False)
        tk.Label(
            self.media_sidebar, text="展示视频", background=self.SURFACE,
            foreground=self.INK, font=("Segoe UI", 11, "bold"), anchor="w",
        ).pack(fill="x", padx=10, pady=(10, 2))
        tk.Label(
            self.media_sidebar, text="选择原始素材或已完成的展示案例。",
            background=self.SURFACE, foreground=self.MUTED,
            font=("Segoe UI", 9), anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 16))
        tk.Label(
            self.media_sidebar, text="可用素材", background=self.SURFACE,
            foreground=self.INK, font=("Segoe UI", 10, "bold"), anchor="w",
        ).pack(fill="x", padx=10)
        tk.Label(
            self.media_sidebar, text="双击后开始本机实时处理",
            background=self.SURFACE, foreground=self.MUTED,
            font=("Segoe UI", 8), anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 7))

        list_holder = tk.Frame(self.media_sidebar, background=self.SURFACE)
        list_holder.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.media_list = tk.Listbox(
            list_holder, background="#fbfcfd", foreground=self.INK,
            selectbackground="#e7f1fb", selectforeground=self.INK,
            highlightbackground=self.BORDER, highlightthickness=1,
            borderwidth=0, activestyle="none", exportselection=False,
            font=("Microsoft YaHei UI", 9), selectmode=tk.SINGLE,
        )
        scrollbar = tk.Scrollbar(list_holder, orient="vertical", command=self.media_list.yview)
        self.media_list.configure(yscrollcommand=scrollbar.set)
        self.media_list.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.media_list.bind("<<ListboxSelect>>", self._select_listed_media)
        self.media_list.bind("<Double-Button-1>", self._play_selected_media)

        actions = tk.Frame(self.media_sidebar, background=self.SURFACE)
        actions.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(
            actions, text="演示选中视频", command=self._play_selected_media,
            background=self.SURFACE, foreground=self.INK,
            activebackground="#fff0df", activeforeground=self.ACCENT,
            highlightbackground=self.BORDER, relief="groove",
            font=("Microsoft YaHei UI", 9), padx=8, pady=4,
        ).pack(side="left")
        tk.Button(
            actions, text="刷新", command=self._refresh_media_entries,
            background=self.SURFACE, foreground=self.INK,
            activebackground="#fff0df", activeforeground=self.ACCENT,
            highlightbackground=self.BORDER, relief="groove",
            font=("Microsoft YaHei UI", 9), padx=20, pady=4,
        ).pack(side="right")
        self._refresh_media_entries()

    def _refresh_media_entries(self) -> None:
        """Rebuild the one selectable list, retaining selection when possible."""
        selected_path = self._selected_media.path if self._selected_media is not None else None
        entries = [
            ShowcaseVideoEntry(path=path, label=title, source="formal_case")
            for title, path in self._case_paths.items()
        ]
        seen_paths = {str(entry.path.resolve()) for entry in entries}
        for entry in library_entries(self.project_root):
            resolved = str(entry.path.resolve())
            if resolved not in seen_paths:
                entries.append(entry)
                seen_paths.add(resolved)
        self._media_entries = entries
        self.media_list.delete(0, tk.END)
        selected_index: int | None = None
        for index, entry in enumerate(entries):
            self.media_list.insert(tk.END, entry.label)
            if selected_path is not None and entry.path == selected_path:
                selected_index = index
        if selected_index is not None:
            self.media_list.selection_set(selected_index)
            self.media_list.activate(selected_index)
            self.media_list.see(selected_index)

    def _select_listed_media(self, _event=None) -> None:
        selected = self.media_list.curselection()
        if not selected:
            return
        entry = self._media_entries[selected[0]]
        if self.video_path != entry.path:
            self.stop()
            self.video_path = entry.path
            self._reset_timeline()
            self.image.configure(
                image="", text=f"已选择：{entry.label}\n双击右侧列表或点击“开始”进行本机实时分析",
            )
        self._selected_media = entry
        self.playback_status.set(f"已选择：{entry.label}")

    def _play_selected_media(self, _event=None) -> None:
        self._select_listed_media()
        if self.video_path is None:
            self.playback_status.set("请先从右侧“可用素材”列表选择视频")
            return
        self.start_or_resume()

    def _place_toolbar(self) -> None:
        # Keep the controls visible below the Dashboard and above the timeline.
        if not self._toolbar_visible:
            self.toolbar.pack(side="bottom", fill="x", padx=8, pady=(0, 3))
        self._toolbar_visible = True

    def _reveal_toolbar(self, _event=None) -> None:
        if not self._toolbar_visible:
            self._place_toolbar()

    def _hide_toolbar(self, _event=None) -> None:
        self.toolbar.pack_forget()
        self._toolbar_visible = False
        self._hide_toolbar_after = None

    def toggle_fullscreen(self) -> None:
        top = self.winfo_toplevel()
        callback = getattr(top, "toggle_showcase_fullscreen", None)
        if callback is not None:
            callback()

    def set_fullscreen(self, enabled: bool) -> None:
        """Hide the side list and chrome only in presentation fullscreen."""
        if enabled:
            self.header.pack_forget()
            self.footer.pack_forget()
            self.media_sidebar.pack_forget()
        else:
            self.header.pack(side="top", fill="x", before=self.content)
            self.footer.pack(side="bottom", fill="x", padx=8, pady=(0, 3))
            self.media_sidebar.pack(side="right", fill="y", padx=(6, 0))
        self.after_idle(self._render_last_frame)

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

    def _toggle_play_shortcut(self, _event=None):
        if not self._pi_poll_active:
            return None
        if self.worker.running:
            self.toggle_pause()
        else:
            self.start_or_resume()
        return "break"

    def _bridge_endpoint(self) -> str:
        base = TeacherRemoteSettingsStore(self.project_root).load().base_url
        host = base.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        return f"http://{host}:8781/api/vision"

    def _start_worker(self, start_time_seconds: float = 0.0) -> None:
        assert self.video_path is not None
        self.bridge_key = (
            os.environ.get("HUIAN_REMOTE_VISION_KEY", "")
            or ShowcaseBridgeSettingsStore(self.project_root).load().bridge_key
        )
        self.worker.start(
            self.video_path,
            bridge_endpoint=self._bridge_endpoint(),
            bridge_key=self.bridge_key,
            start_time_seconds=max(0.0, start_time_seconds),
        )
        self._running = True

    def start_or_resume(self) -> None:
        if self.video_path is None:
            self.playback_status.set("请先从右侧“可用素材”列表选择视频")
            return
        if self.worker.running and self.worker.paused:
            self.worker.pause(False)
            self.playback_status.set("继续播放")
            return
        if self.worker.running:
            return
        self._set_timeline_position(0.0)
        self._start_worker()
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
            image = showcase_image_from_bgr(packet.frame_bgr)
            max_width = max(320, self.stage.winfo_width() - 8)
            max_height = max(240, self.stage.winfo_height() - 8)
            image.thumbnail((max_width, max_height))
            self._photo = ImageTk.PhotoImage(image)
            self.image.configure(image=self._photo, text="")
            self._set_timeline_position(packet.source_time)
            total = packet.status.get("total_people", "—")
            risk = packet.status.get("vision_risk", "NORMAL")
            self.playback_status.set(f"{packet.source_time:.1f} s · {total} 人 · {risk}")
        except Exception as error:
            self.playback_status.set("画面显示失败：" + str(error))

    def _fetch_pi_status(self) -> None:
        try:
            settings = TeacherRemoteSettingsStore(self.project_root).load()
            result: tuple[str, object] = (
                "pi", TeacherRemoteClient(settings.base_url, timeout_seconds=0.8).status(),
            )
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
            threading.Thread(
                target=self._fetch_pi_status, name="huian-pi-status", daemon=True,
            ).start()
        self._schedule_pi_poll(1500)

    def _drain_events(self) -> None:
        # A UI pass may receive more than one completed frame. Rendering each
        # one would create several PIL/Tk images and make the Dashboard lag;
        # show only the newest frame while preserving control events.
        latest_frame: ShowcaseFrame | None = None
        terminal_status: str | None = None
        show_error: str | None = None
        while True:
            try:
                event: ShowcaseEvent = self.worker.events.get_nowait()
            except queue.Empty:
                break
            if event.kind == "started":
                data = dict(event.value or {})
                self._set_timeline_duration(data.get("duration_seconds"))
                self.playback_status.set(
                    "本机实时分析 · 硬件联动已就绪"
                    if data.get("hardware") else "本机实时分析",
                )
            elif event.kind == "seeked":
                self.playback_status.set(f"已跳转到 {format_showcase_time(float(event.value or 0.0))}")
            elif event.kind == "frame" and isinstance(event.value, ShowcaseFrame):
                latest_frame = event.value
            elif event.kind == "finished":
                self._running = False
                terminal_status = "播放结束"
            elif event.kind == "error":
                self._running = False
                latest_frame = None
                terminal_status = "无法启动"
                show_error = str(event.value)
        if latest_frame is not None:
            self._render_frame(latest_frame)
        if terminal_status is not None:
            self.playback_status.set(terminal_status)
        if show_error is not None:
            messagebox.showerror("现场展示", show_error, parent=self)
        while True:
            try:
                kind, value = self._pi_events.get_nowait()
            except queue.Empty:
                break
            if kind == "pi":
                self.pi_status.set(showcase_status_text(value if isinstance(value, dict) else None))
        if self.winfo_exists():
            self.after(self.UI_POLL_MS, self._drain_events)
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