"""Tkinter page for the YOLO / ByteTrack teaching experiment."""
from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from teaching_console.ui_zoom import CONTROL_MASK, scaled_value
from teaching_console.services.vision_teaching_service import (
    MODE_DETECT,
    MODE_RAW,
    MODE_TRACK,
    FramePacket,
    VisionTeachingError,
    VisionTeachingService,
    VisionTeachingWorker,
    find_example_video,
    load_vision_config,
    teaching_cases,
)


MODE_LABELS = {
    MODE_RAW: "原始画面",
    MODE_DETECT: "YOLO 检测",
    MODE_TRACK: "YOLO + ByteTrack",
}

BASE_VIDEO_SIZE = (640, 420)


class VisionTrackingPage(ttk.Frame):
    """A UI shell; the worker is the only thread that touches video/model work."""

    def __init__(self, master, root_path: Path, open_source, copy_path) -> None:
        super().__init__(master)
        self.root_path = root_path
        self.open_source = open_source
        self.copy_path = copy_path
        self.config = load_vision_config(root_path)
        self.worker = VisionTeachingWorker(VisionTeachingService(root_path))
        self.video = None
        self.current_case: tuple[str, str] | None = None
        self.cases = teaching_cases(root_path)
        self.frame_index = 0
        self.mode_var = tk.StringVar(value=MODE_RAW)
        self.status_var = tk.StringVar(value="准备就绪：尚未加载模型")
        self.video_var = tk.StringVar(value="尚未选择视频")
        self.frame_var = tk.StringVar(value="帧：—")
        self.model_var = tk.StringVar(value=f"模型：{self.config.model_path.name}（按需加载）")
        self.learning_var = tk.StringVar()
        self.source_var = tk.StringVar()
        self.seek_var = tk.DoubleVar(value=0)
        self.playing = False
        self.busy = False
        self.closing = False
        self.request_token = 0
        self._image = None
        self._display_frame_bgr = None
        self._zoom_factor = 1.0
        self._wheel_tag = f"VisionTrackingWheel_{id(self)}"
        self._wheel_targets = []
        self._build_scroll_container()
        self._build()
        self._register_wheel_targets()
        self.bind_class(self._wheel_tag, "<MouseWheel>", self._on_mousewheel)
        self.bind("<Map>", self._activate_mousewheel, add="+")
        self.bind("<Unmap>", self._deactivate_mousewheel, add="+")
        self._set_learning_text()
        self.after(40, self._drain_worker)
        self.after(80, self.load_example)

    def _build_scroll_container(self) -> None:
        """Keep the navigation outside this page while its main content scrolls."""
        self._scroll_canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self._scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._scroll_canvas.yview)
        self._scroll_canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scroll_canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")
        self._scroll_content = ttk.Frame(self._scroll_canvas, padding=12)
        self._scroll_window = self._scroll_canvas.create_window((0, 0), window=self._scroll_content, anchor="nw")
        self._scroll_content.bind("<Configure>", self._sync_scrollregion)
        self._scroll_canvas.bind("<Configure>", self._fit_scroll_content)

    def _sync_scrollregion(self, _event=None) -> None:
        self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

    def _fit_scroll_content(self, event) -> None:
        self._scroll_canvas.itemconfigure(self._scroll_window, width=event.width)
        self._sync_scrollregion()

    def _register_wheel_targets(self) -> None:
        def visit(widget) -> None:
            self._wheel_targets.append(widget)
            for child in widget.winfo_children():
                visit(child)
        visit(self)

    def _activate_mousewheel(self, _event=None) -> None:
        for widget in self._wheel_targets:
            if widget.winfo_exists() and self._wheel_tag not in widget.bindtags():
                widget.bindtags((self._wheel_tag, *widget.bindtags()))

    def _deactivate_mousewheel(self, _event=None) -> None:
        for widget in self._wheel_targets:
            if widget.winfo_exists() and self._wheel_tag in widget.bindtags():
                widget.bindtags(tuple(tag for tag in widget.bindtags() if tag != self._wheel_tag))

    def _on_mousewheel(self, event):
        if event.state & CONTROL_MASK:
            return None
        if self.winfo_ismapped() and event.delta:
            steps = -int(event.delta / 120)
            self._scroll_canvas.yview_scroll(steps or (-1 if event.delta > 0 else 1), "units")
            return "break"
        return None

    def _build(self) -> None:
        content = self._scroll_content
        ttk.Label(content, text="YOLO / Tracking 实验", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            content,
            text="教学页真实调用仓库中的 PersonDetector.detect() 或 PersonTracker.track()；两者是并列入口，不是串行的 detector → tracker。",
            wraplength=1080,
        ).pack(anchor="w", pady=(2, 8))
        controls = ttk.Frame(content); controls.pack(fill="x")
        ttk.Button(controls, text="选择本地视频", command=self.choose_video).pack(side="left")
        ttk.Button(controls, text="使用默认案例 000327", command=self.load_example).pack(side="left", padx=5)
        ttk.Button(controls, text="重新加载模型", command=self.reload_models).pack(side="left")
        ttk.Label(controls, textvariable=self.status_var).pack(side="right")
        cases = ttk.Frame(content); cases.pack(fill="x", pady=(6, 0))
        ttk.Label(cases, text="固定教学案例：").pack(side="left")
        for code, purpose, path in self.cases:
            ttk.Button(cases, text=f"{code}：{purpose}", command=lambda c=code, p=purpose, v=path: self.load_case(c, p, v)).pack(side="left", padx=(0, 5))
        ttk.Label(content, textvariable=self.video_var, foreground="#555555", wraplength=1080).pack(anchor="w", pady=(5, 0))
        ttk.Label(content, textvariable=self.model_var, foreground="#555555", wraplength=1080).pack(anchor="w")

        body = ttk.Panedwindow(content, orient="horizontal"); body.pack(fill="both", expand=True, pady=(10, 0))
        viewer, details = ttk.Frame(body), ttk.Frame(body)
        body.add(viewer, weight=3); body.add(details, weight=2)
        self._build_viewer(viewer)
        self._build_details(details)

        modes = ttk.LabelFrame(content, text="实验模式", padding=8); modes.pack(fill="x", pady=(8, 0))
        for mode in (MODE_RAW, MODE_DETECT, MODE_TRACK):
            ttk.Radiobutton(modes, text=MODE_LABELS[mode], variable=self.mode_var, value=mode, command=self.change_mode).pack(side="left", padx=(0, 16))
        ttk.Label(modes, text="切换、回退或拖动视频时，追踪器会重置；Track ID 重新编号是正常现象。", foreground="#665500").pack(side="left")

        navigation = ttk.Frame(content); navigation.pack(fill="x", pady=(8, 0))
        ttk.Button(navigation, text="上一帧", command=self.previous_frame).pack(side="left")
        self.play_button = ttk.Button(navigation, text="播放", command=self.toggle_play); self.play_button.pack(side="left", padx=5)
        ttk.Button(navigation, text="下一帧", command=self.next_frame).pack(side="left")
        self.seek = ttk.Scale(navigation, variable=self.seek_var, from_=0, to=1, command=lambda _value: None)
        self.seek.pack(side="left", fill="x", expand=True, padx=16)
        self.seek.bind("<ButtonRelease-1>", self.seek_release)
        ttk.Label(navigation, textvariable=self.frame_var, width=25).pack(side="right")

    def _build_viewer(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="视频画面", padding=6); box.pack(fill="both", expand=True, padx=(0, 6))
        self.canvas_label = ttk.Label(box, text="正在准备示例视频…", anchor="center")
        self.canvas_label.pack(fill="both", expand=True)

    def _build_details(self, parent) -> None:
        teach = ttk.LabelFrame(parent, text="本模式教学说明", padding=8); teach.pack(fill="x", padx=(6, 0))
        ttk.Label(teach, textvariable=self.learning_var, wraplength=390, justify="left").pack(anchor="w")
        source = ttk.LabelFrame(parent, text="真实源码入口", padding=8); source.pack(fill="x", padx=(6, 0), pady=(8, 0))
        ttk.Label(source, textvariable=self.source_var, wraplength=390, justify="left").pack(anchor="w")
        buttons = ttk.Frame(source); buttons.pack(anchor="w", pady=(6, 0))
        ttk.Button(buttons, text="打开源码", command=self.open_current_source).pack(side="left")
        ttk.Button(buttons, text="复制路径", command=self.copy_current_source).pack(side="left", padx=5)
        results = ttk.LabelFrame(parent, text="当前帧结果", padding=6); results.pack(fill="both", expand=True, padx=(6, 0), pady=(8, 0))
        self.result_note = tk.StringVar(value="尚未读取帧")
        ttk.Label(results, textvariable=self.result_note, foreground="#555555", wraplength=390).pack(anchor="w", pady=(0, 4))
        self.table = ttk.Treeview(results, columns=("id", "confidence", "bbox", "anchor"), show="headings", height=12)
        self.table.heading("id", text="检测序号")
        self.table.heading("confidence", text="置信度")
        self.table.heading("bbox", text="边界框 x1,y1,x2,y2")
        self.table.heading("anchor", text="底部中心")
        self.table.column("id", width=76, anchor="center")
        self.table.column("confidence", width=70, anchor="center")
        self.table.column("bbox", width=160, anchor="center")
        self.table.column("anchor", width=100, anchor="center")
        self.table.pack(fill="both", expand=True)

    def choose_video(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="选择本地视频", initialdir=str(self.root_path),
            filetypes=(("视频文件", "*.mp4 *.avi *.mov *.mkv"), ("所有文件", "*.*")),
        )
        if path:
            self.current_case = None
            self.load_video(Path(path))

    def load_example(self) -> None:
        for code, purpose, path in self.cases:
            if code == "000327":
                self.load_case(code, purpose, path)
                return
        try:
            candidate = find_example_video(self.root_path)
            if candidate is None:
                raise VisionTeachingError("仓库中未找到可用示例视频；请点击“选择本地视频”。")
            self.current_case = None
            self.load_video(candidate)
        except VisionTeachingError as error:
            self._show_error(error)

    def load_case(self, code: str, purpose: str, path: Path) -> None:
        self.current_case = (code, purpose)
        self.load_video(path)

    def load_video(self, path: Path) -> None:
        self.stop_play()
        self._submit("open_video", path)
        self.status_var.set("正在后台打开视频…")

    def reload_models(self) -> None:
        self.stop_play()
        self._submit("reload_models")
        self.status_var.set("已请求释放模型；下次检测/追踪将重新按需加载")

    def change_mode(self) -> None:
        self.stop_play()
        self._set_learning_text()
        if self.video is not None:
            self._request_frame(self.frame_index, sequential=False)

    def previous_frame(self) -> None:
        self.stop_play()
        self._request_frame(max(0, self.frame_index - 1), sequential=False)

    def next_frame(self) -> None:
        sequential = self.mode_var.get() == MODE_TRACK
        self._request_frame(self.frame_index + 1, sequential=sequential)

    def toggle_play(self) -> None:
        if self.playing:
            self.stop_play(); return
        if self.video is None:
            return
        self.playing = True; self.play_button.configure(text="暂停")
        self._request_frame(self.frame_index + 1, sequential=self.mode_var.get() == MODE_TRACK)

    def stop_play(self) -> None:
        self.playing = False
        if hasattr(self, "play_button"):
            self.play_button.configure(text="播放")

    def seek_release(self, _event) -> None:
        self.stop_play()
        self._request_frame(int(round(self.seek_var.get())), sequential=False)

    def _request_frame(self, index: int, sequential: bool) -> None:
        if self.video is None or self.busy:
            return
        index = max(0, min(index, self.video.total_frames - 1))
        self._submit("read_frame", index, self.mode_var.get(), sequential)
        self.status_var.set(f"正在处理第 {index + 1} 帧…")

    def _submit(self, operation: str, *args) -> None:
        self.request_token += 1
        self.busy = True
        self.worker.submit(self.request_token, operation, *args)

    def _drain_worker(self) -> None:
        if self.closing:
            return
        while True:
            try:
                result = self.worker.results.get_nowait()
            except queue.Empty:
                break
            if result.token != self.request_token:
                continue
            self.busy = False
            if result.error:
                self.stop_play(); self._show_error(result.error); continue
            self._handle_result(result.operation, result.value)
        self.after(40, self._drain_worker)

    def _handle_result(self, operation: str, value) -> None:
        if operation == "open_video":
            self.video = value; self.frame_index = 0
            self.seek.configure(to=max(0, value.total_frames - 1)); self.seek_var.set(0)
            case_text = "本地自选视频" if self.current_case is None else f"教学案例 {self.current_case[0]}：{self.current_case[1]}"
            self.video_var.set(f"{case_text}  |  视频：{value.path}  |  {value.width}×{value.height}  |  {value.fps:.2f} FPS  |  {value.total_frames} 帧")
            self.status_var.set("视频已打开；请选择模式后逐帧实验")
            self._request_frame(0, sequential=False)
        elif operation == "read_frame":
            self._render_packet(value)
        elif operation == "reload_models":
            self.model_var.set(f"模型：{self.config.model_path.name}（已释放，按需重新加载）")

    def _render_packet(self, packet: FramePacket) -> None:
        self.frame_index = packet.frame_index
        self.seek_var.set(packet.frame_index)
        self.frame_var.set(f"帧：{packet.frame_index + 1}/{packet.video.total_frames}  |  {packet.seconds:.2f} 秒")
        self._render_image(packet.frame_bgr)
        self._render_rows(packet)
        if packet.mode == MODE_RAW:
            self.status_var.set("原始画面：未加载 YOLO 模型")
        else:
            self.model_var.set(f"模型：{self.config.model_path.name}  |  person-only  |  conf={self.config.confidence:.2f}")
            suffix = "；追踪器因视频不连续而重置，ID 可能重新编号" if packet.tracker_reset else ""
            self.status_var.set(f"{MODE_LABELS[packet.mode]}：已处理 {len(packet.rows)} 人{suffix}")
        if self.playing:
            if packet.frame_index + 1 >= packet.video.total_frames:
                self.stop_play()
            else:
                self.after(120, lambda: self._request_frame(packet.frame_index + 1, sequential=packet.mode == MODE_TRACK))

    def _render_image(self, frame_bgr) -> None:
        self._display_frame_bgr = frame_bgr
        try:
            from PIL import Image, ImageTk
            image = Image.fromarray(frame_bgr[:, :, ::-1])
            image.thumbnail(tuple(scaled_value(value, self._zoom_factor) for value in BASE_VIDEO_SIZE))
            self._image = ImageTk.PhotoImage(image)
            self.canvas_label.configure(image=self._image, text="")
        except Exception as error:
            self.canvas_label.configure(image="", text=f"无法显示画面：{error}")

    def on_zoom_changed(self, factor: float) -> None:
        self._zoom_factor = factor
        if self._display_frame_bgr is not None:
            self._render_image(self._display_frame_bgr)
        self.after_idle(self._sync_scrollregion)

    def _render_rows(self, packet: FramePacket) -> None:
        for item in self.table.get_children():
            self.table.delete(item)
        if packet.mode == MODE_TRACK:
            self.table.heading("id", text="Track ID")
        else:
            self.table.heading("id", text="检测序号")
        if not packet.rows:
            self.result_note.set("当前帧未检测到 person；表格已清空，不保留上一帧结果。")
            return
        self.result_note.set(f"当前帧检测到 {len(packet.rows)} 个 person。")
        for row in packet.rows:
            identity = str(row.track_id) if row.track_id is not None else str(row.index)
            self.table.insert("", "end", values=(identity, f"{row.confidence:.2f}", row.bbox_text, row.anchor_text))

    def _set_learning_text(self) -> None:
        mode = self.mode_var.get()
        if mode == MODE_RAW:
            self.learning_var.set("原始画面只读取视频帧，不执行模型推理。可先观察遮挡、光照、楼道透视如何影响后续检测。")
            self.source_var.set("视频读取与课堂服务：teaching_console/services/vision_teaching_service.py\n模型配置：rpi_app/config.json")
        elif mode == MODE_DETECT:
            self.learning_var.set("单帧 YOLO person 检测：PersonDetector.detect() 每帧独立输出边界框与置信度。confidence 不是“身份可信度”。")
            self.source_var.set("真实调用：rpi_app/vision/detector.py → PersonDetector.detect()\n配置：rpi_app/config.json（model_path、confidence）")
        else:
            self.learning_var.set("视频 YOLO + ByteTrack：PersonTracker.track() 内部调用 model.track(..., persist=True)。Track ID 只是在当前连续视频段内的临时关联编号，不等于真实身份。")
            self.source_var.set("真实调用：rpi_app/vision/tracker.py → PersonTracker.track()\n配置：rpi_app/config.json（tracker=bytetrack.yaml、confidence）")

    def _current_source_path(self) -> Path:
        if self.mode_var.get() == MODE_DETECT:
            return self.root_path / "rpi_app" / "vision" / "detector.py"
        if self.mode_var.get() == MODE_TRACK:
            return self.root_path / "rpi_app" / "vision" / "tracker.py"
        return self.root_path / "rpi_app" / "config.json"

    def open_current_source(self) -> None:
        self.open_source(self._current_source_path())

    def copy_current_source(self) -> None:
        self.copy_path(self._current_source_path())

    def _show_error(self, error: Exception) -> None:
        self.status_var.set(f"错误：{error}")
        messagebox.showerror("YOLO / Tracking 实验", str(error), parent=self)

    def close(self) -> None:
        self.closing = True
        self._deactivate_mousewheel()
        self.unbind_class(self._wheel_tag, "<MouseWheel>")
        self.stop_play()
        self.worker.close()
