"""Tkinter teaching page for Track ID → trajectory → direction."""
from __future__ import annotations

import math
import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from teaching_console.services.trajectory_teaching_service import (
    LAYER_DIRECTION,
    LAYER_RAW,
    LAYER_TRACK,
    LAYER_TRAIL,
    TrajectoryFramePacket,
    TrajectoryTeachingService,
    active_track_ids,
    motion_display_data,
)
from teaching_console.services.vision_teaching_service import (
    VisionTeachingError,
    VisionTeachingWorker,
    find_example_video,
    load_vision_config,
    teaching_cases,
)


LAYER_LABELS = {
    LAYER_RAW: "原始画面",
    LAYER_TRACK: "Track ID",
    LAYER_TRAIL: "显示轨迹",
    LAYER_DIRECTION: "显示方向",
}


def format_heading(value: object) -> str:
    return "—" if value is None else f"{float(value):.1f}°"


class TrajectoryDirectionPage(ttk.Frame):
    """A scrollable UI; the worker alone owns capture, ByteTrack and trajectories."""

    def __init__(self, master, root_path: Path, open_source, copy_path) -> None:
        super().__init__(master)
        self.root_path = Path(root_path)
        self.open_source = open_source
        self.copy_path = copy_path
        self.config = load_vision_config(self.root_path)
        self.worker = VisionTeachingWorker(TrajectoryTeachingService(self.root_path))
        self.video = None
        self.cases = teaching_cases(self.root_path)
        self.current_case: tuple[str, str] | None = None
        self.frame_index = 0
        self.layer_var = tk.StringVar(value=LAYER_RAW)
        self.selected_track_var = tk.StringVar()
        self.status_var = tk.StringVar(value="准备就绪：请选择视频或使用 000327")
        self.video_var = tk.StringVar(value="尚未选择视频")
        self.model_var = tk.StringVar(value=f"模型：{self.config.model_path.name}（按需加载）")
        self.frame_var = tk.StringVar(value="帧：—")
        self.detail_var = tk.StringVar(value="当前没有活跃 Track ID。")
        self.teaching_var = tk.StringVar()
        self.source_var = tk.StringVar()
        self.seek_var = tk.DoubleVar(value=0)
        self.playing = False
        self.busy = False
        self.closing = False
        self.request_token = 0
        self._image = None
        self._packet: TrajectoryFramePacket | None = None
        self._wheel_tag = f"TrajectoryDirectionWheel_{id(self)}"
        self._wheel_targets: list[tk.Misc] = []
        self._build_scroll_container()
        self._build()
        self._register_wheel_targets()
        self.bind_class(self._wheel_tag, "<MouseWheel>", self._on_mousewheel)
        self.bind("<Map>", self._activate_mousewheel, add="+")
        self.bind("<Unmap>", self._deactivate_mousewheel, add="+")
        self._set_teaching_text()
        self.after(40, self._drain_worker)
        self.after(80, self.load_example)

    def _build_scroll_container(self) -> None:
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y")
        self.body = ttk.Frame(self.canvas, padding=12)
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.window, width=event.width))

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
        if self.winfo_ismapped() and event.delta:
            steps = -int(event.delta / 120)
            self.canvas.yview_scroll(steps or (-1 if event.delta > 0 else 1), "units")
            return "break"
        return None

    def _build(self) -> None:
        ttk.Label(self.body, text="轨迹 / Direction 实验", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            self.body,
            text="真实链路：PersonTracker.track() → bottom-center anchor → TrajectoryAnalyzer.update() → motion_state / heading_angle。",
            wraplength=1080,
        ).pack(anchor="w", pady=(2, 8))
        controls = ttk.Frame(self.body); controls.pack(fill="x")
        ttk.Button(controls, text="选择本地视频", command=self.choose_video).pack(side="left")
        ttk.Button(controls, text="使用默认案例 000327", command=self.load_example).pack(side="left", padx=5)
        ttk.Button(controls, text="重新加载模型", command=self.reload_models).pack(side="left")
        ttk.Label(controls, textvariable=self.status_var).pack(side="right")
        ttk.Label(self.body, textvariable=self.video_var, wraplength=1080, foreground="#555555").pack(anchor="w", pady=(5, 0))
        ttk.Label(self.body, textvariable=self.model_var, wraplength=1080, foreground="#555555").pack(anchor="w")

        content = ttk.Panedwindow(self.body, orient="horizontal"); content.pack(fill="both", expand=True, pady=(10, 0))
        viewer, details = ttk.Frame(content), ttk.Frame(content)
        content.add(viewer, weight=3); content.add(details, weight=2)
        self._build_viewer(viewer)
        self._build_details(details)

        layers = ttk.LabelFrame(self.body, text="观察层级", padding=8); layers.pack(fill="x", pady=(8, 0))
        for layer in (LAYER_RAW, LAYER_TRACK, LAYER_TRAIL, LAYER_DIRECTION):
            ttk.Radiobutton(layers, text=LAYER_LABELS[layer], variable=self.layer_var, value=layer, command=self.change_layer).pack(side="left", padx=(0, 16))
        ttk.Label(layers, text="跳转、回退、换视频后会重建 Track ID 与轨迹。", foreground="#665500").pack(side="left")

        nav = ttk.Frame(self.body); nav.pack(fill="x", pady=(8, 0))
        ttk.Button(nav, text="上一帧", command=self.previous_frame).pack(side="left")
        self.play_button = ttk.Button(nav, text="播放", command=self.toggle_play); self.play_button.pack(side="left", padx=5)
        ttk.Button(nav, text="下一帧", command=self.next_frame).pack(side="left")
        self.seek = ttk.Scale(nav, variable=self.seek_var, from_=0, to=1); self.seek.pack(side="left", fill="x", expand=True, padx=16)
        self.seek.bind("<ButtonRelease-1>", self.seek_release)
        ttk.Label(nav, textvariable=self.frame_var, width=25).pack(side="right")

    def _build_viewer(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="视频画面", padding=6); box.pack(fill="both", expand=True, padx=(0, 6))
        self.image_label = ttk.Label(box, text="正在准备示例视频…", anchor="center")
        self.image_label.pack(fill="both", expand=True)

    def _build_details(self, parent) -> None:
        select = ttk.LabelFrame(parent, text="当前观察 Track ID", padding=8); select.pack(fill="x", padx=(6, 0))
        self.track_combo = ttk.Combobox(select, textvariable=self.selected_track_var, state="readonly", width=18)
        self.track_combo.pack(anchor="w"); self.track_combo.bind("<<ComboboxSelected>>", self._on_track_selected)
        detail = ttk.LabelFrame(parent, text="真实轨迹与方向数据", padding=8); detail.pack(fill="both", expand=True, padx=(6, 0), pady=(8, 0))
        ttk.Label(detail, textvariable=self.detail_var, wraplength=400, justify="left").pack(anchor="w")
        teach = ttk.LabelFrame(parent, text="课堂观察", padding=8); teach.pack(fill="x", padx=(6, 0), pady=(8, 0))
        ttk.Label(teach, textvariable=self.teaching_var, wraplength=400, justify="left").pack(anchor="w")
        ttk.Label(teach, text="图像坐标：左上角 (0,0)，x 向右增加，y 向下增加。\n(0,0) ┌────→ x\n      │\n      ↓ y", justify="left").pack(anchor="w", pady=(6, 0))
        source = ttk.LabelFrame(parent, text="真实源码入口", padding=8); source.pack(fill="x", padx=(6, 0), pady=(8, 0))
        ttk.Label(source, textvariable=self.source_var, wraplength=400, justify="left").pack(anchor="w")
        buttons = ttk.Frame(source); buttons.pack(anchor="w", pady=(6, 0))
        ttk.Button(buttons, text="打开源码", command=self.open_current_source).pack(side="left")
        ttk.Button(buttons, text="复制路径", command=self.copy_current_source).pack(side="left", padx=5)

    def choose_video(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="选择本地视频", initialdir=str(self.root_path), filetypes=(("视频文件", "*.mp4 *.avi *.mov *.mkv"), ("所有文件", "*.*")))
        if path:
            self.current_case = None
            self.load_video(Path(path))

    def load_example(self) -> None:
        for code, purpose, path in self.cases:
            if code == "000327":
                self.current_case = (code, purpose)
                self.load_video(path)
                return
        try:
            self.current_case = None
            candidate = find_example_video(self.root_path)
            if candidate is None:
                raise VisionTeachingError("仓库中未找到原始教学视频；请点击“选择本地视频”。")
            self.load_video(candidate)
        except VisionTeachingError as error:
            self._show_error(error)

    def load_video(self, path: Path) -> None:
        self.stop_play(); self._submit("open_video", path); self.status_var.set("正在后台打开视频…")

    def reload_models(self) -> None:
        self.stop_play(); self._submit("reload_models"); self.status_var.set("已释放模型和轨迹状态；下次 Track ID 将重新建立")

    def change_layer(self) -> None:
        self.stop_play(); self._set_teaching_text()
        if self.video is not None:
            self._request_frame(self.frame_index, sequential=False)

    def previous_frame(self) -> None:
        self.stop_play(); self._request_frame(max(0, self.frame_index - 1), sequential=False)

    def next_frame(self) -> None:
        self._request_frame(self.frame_index + 1, sequential=self.layer_var.get() != LAYER_RAW)

    def toggle_play(self) -> None:
        if self.playing:
            self.stop_play(); return
        if self.video is None:
            return
        self.playing = True; self.play_button.configure(text="暂停")
        self._request_frame(self.frame_index + 1, sequential=self.layer_var.get() != LAYER_RAW)

    def stop_play(self) -> None:
        self.playing = False
        if hasattr(self, "play_button"):
            self.play_button.configure(text="播放")

    def seek_release(self, _event) -> None:
        self.stop_play(); self._request_frame(int(round(self.seek_var.get())), sequential=False)

    def _request_frame(self, index: int, sequential: bool) -> None:
        if self.video is None or self.busy:
            return
        index = max(0, min(index, self.video.total_frames - 1))
        self._submit("read_trajectory_frame", index, self.layer_var.get(), sequential)
        self.status_var.set(f"正在处理第 {index + 1} 帧…")

    def _submit(self, operation: str, *args) -> None:
        self.request_token += 1; self.busy = True; self.worker.submit(self.request_token, operation, *args)

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
            self.video = value; self.frame_index = 0; self.seek.configure(to=max(0, value.total_frames - 1)); self.seek_var.set(0)
            case_text = "本地自选视频" if self.current_case is None else f"教学案例 {self.current_case[0]}：{self.current_case[1]}"
            self.video_var.set(f"{case_text}  |  视频：{value.path}  |  {value.width}×{value.height}  |  {value.fps:.2f} FPS  |  {value.total_frames} 帧")
            self.status_var.set("视频已打开；选择观察层级后逐帧实验")
            self._request_frame(0, sequential=False)
        elif operation == "read_trajectory_frame":
            self._render_packet(value)
        elif operation == "reload_models":
            self.model_var.set(f"模型：{self.config.model_path.name}（已释放，按需重新加载）")

    def _render_packet(self, packet: TrajectoryFramePacket) -> None:
        self._packet = packet; frame = packet.frame; self.frame_index = frame.frame_index; self.seek_var.set(frame.frame_index)
        self.frame_var.set(f"帧：{frame.frame_index + 1}/{frame.video.total_frames}  |  {frame.seconds:.2f} 秒")
        self._render_image(self._draw_layers(frame.frame_bgr, packet))
        self._refresh_track_choices(packet)
        if self.layer_var.get() == LAYER_RAW:
            self.status_var.set("原始画面：未加载 YOLO 模型")
        else:
            self.model_var.set(f"模型：{self.config.model_path.name}  | person-only | conf={self.config.confidence:.2f}")
            reset_note = "；非连续跳转已重建 Track ID 与轨迹" if packet.trajectory_reset else ""
            self.status_var.set(f"{LAYER_LABELS[self.layer_var.get()]}：当前 {len(frame.rows)} 人{reset_note}")
        if self.playing:
            if frame.frame_index + 1 >= frame.video.total_frames:
                self.stop_play()
            else:
                self.after(120, lambda: self._request_frame(frame.frame_index + 1, sequential=self.layer_var.get() != LAYER_RAW))

    def _draw_layers(self, frame_bgr, packet: TrajectoryFramePacket):
        if self.layer_var.get() not in {LAYER_TRAIL, LAYER_DIRECTION}:
            return frame_bgr
        try:
            import cv2
            image = frame_bgr.copy()
            for motion in packet.motions.values():
                data = motion_display_data(motion, packet.frame.video.width, packet.frame.video.height)
                points = [(x, y) for _time, x, y in data["trail"]]
                if len(points) > 1:
                    for start, end in zip(points, points[1:]):
                        cv2.line(image, start, end, (255, 170, 0), 2)
                if points:
                    cv2.circle(image, points[-1], 4, (255, 170, 0), -1)
                if self.layer_var.get() == LAYER_DIRECTION and data["motion_state"] == "MOVING" and data["heading_angle"] is not None:
                    angle = math.radians(float(data["heading_angle"]))
                    end = (data["anchor"][0] + int(45 * math.cos(angle)), data["anchor"][1] + int(45 * math.sin(angle)))
                    cv2.arrowedLine(image, data["anchor"], end, (220, 70, 255), 2, tipLength=0.25)
                    cv2.putText(image, f"{format_heading(data['heading_angle'])} {data['motion_state']}", (data["anchor"][0] + 6, data["anchor"][1] + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 70, 255), 2)
            return image
        except Exception:
            return frame_bgr

    def _render_image(self, frame_bgr) -> None:
        try:
            from PIL import Image, ImageTk
            image = Image.fromarray(frame_bgr[:, :, ::-1]); image.thumbnail((640, 420))
            self._image = ImageTk.PhotoImage(image); self.image_label.configure(image=self._image, text="")
        except Exception as error:
            self.image_label.configure(image="", text=f"无法显示画面：{error}")

    def _refresh_track_choices(self, packet: TrajectoryFramePacket) -> None:
        ids = active_track_ids(packet.frame.rows)
        values = [f"ID {track_id}" for track_id in ids]
        self.track_combo.configure(values=values)
        current = self.selected_track_var.get()
        if current not in values:
            self.selected_track_var.set(values[0] if values else "")
        self._show_selected_track()

    def _on_track_selected(self, _event=None) -> None:
        self._show_selected_track()

    def _selected_track_id(self) -> int | None:
        text = self.selected_track_var.get().replace("ID", "").strip()
        try:
            return int(text)
        except ValueError:
            return None

    def _show_selected_track(self) -> None:
        if self._packet is None:
            self.detail_var.set("当前没有活跃 Track ID。")
            return
        track_id = self._selected_track_id()
        if track_id is None:
            self.detail_var.set("当前帧没有 person；已清空上一帧 Track 与轨迹数据。")
            return
        row = next((item for item in self._packet.frame.rows if item.track_id == track_id), None)
        motion = self._packet.motions.get(track_id)
        if row is None:
            self.detail_var.set("当前选择的 Track 已离开画面。")
            return
        if motion is None:
            self.detail_var.set(f"Track ID：{track_id}\nbbox：{row.bbox_text}\n当前 bottom-center：{row.anchor_text}\n当前为 Track ID 层级：尚未建立轨迹历史。")
            return
        data = motion_display_data(motion, self._packet.frame.video.width, self._packet.frame.video.height)
        history = "\n".join(f"t={time:.2f}  ({x}, {y})" for time, x, y in data["trail"][-8:]) or "—"
        duration = 0.0 if len(data["trail"]) < 2 else data["trail"][-1][0] - data["trail"][0][0]
        self.detail_var.set(
            f"Track ID：{track_id}\n当前 bottom-center：{data['anchor']}\n"
            f"轨迹历史（最近约 {self.worker.service.trajectory_config.get('trajectory_seconds', 2.0)} 秒）：\n{history}\n"
            f"起点：{data['start']}  终点：{data['end']}\n"
            f"Δx = {data['end'][0]} - {data['start'][0]} = {data['dx_pixels']:+d} px\n"
            f"Δy = {data['end'][1]} - {data['start'][1]} = {data['dy_pixels']:+d} px\n"
            f"轨迹持续时间：{duration:.2f} s\n"
            f"正式算法内部：Δx={float(data['dx_norm']):+.4f}，Δy={float(data['dy_norm']):+.4f}（归一化坐标）\n"
            f"heading_angle：{format_heading(data['heading_angle'])}\n"
            f"最终方向状态：{data['motion_state']}"
        )

    def _set_teaching_text(self) -> None:
        layer = self.layer_var.get()
        if layer == LAYER_RAW:
            self.teaching_var.set("原始画面只读取视频帧，不执行模型。先观察楼道中的人和遮挡。")
            self.source_var.set("视频读取：teaching_console/services/vision_teaching_service.py\n配置：rpi_app/config.json")
        elif layer == LAYER_TRACK:
            self.teaching_var.set("连续点下一帧，观察同一个人的 Track ID 是否保持。Track ID 是当前连续视频段的关联编号，不是真实身份。")
            self.source_var.set("真实调用：rpi_app/vision/tracker.py → PersonTracker.track()")
        elif layer == LAYER_TRAIL:
            self.teaching_var.set("选择一个 Track ID，观察它最近几个 bottom-center 位置如何连成轨迹。轨迹只保留最近一小段时间，不是整段视频路线。")
            self.source_var.set("真实调用：rpi_app/vision/trajectory.py → TrajectoryAnalyzer.update()")
        else:
            self.teaching_var.set("比较轨迹起点和终点，观察 Δx / Δy 与最终方向判断。如果一个人几乎没动，系统不应该硬给他一个方向。")
            self.source_var.set("真实调用：TrajectoryAnalyzer.update() 的 motion_state / heading_angle\n阈值：rpi_app/config.json → tracking")

    def _current_source_path(self) -> Path:
        if self.layer_var.get() == LAYER_TRACK:
            return self.root_path / "rpi_app" / "vision" / "tracker.py"
        if self.layer_var.get() in {LAYER_TRAIL, LAYER_DIRECTION}:
            return self.root_path / "rpi_app" / "vision" / "trajectory.py"
        return self.root_path / "rpi_app" / "config.json"

    def open_current_source(self) -> None:
        self.open_source(self._current_source_path())

    def copy_current_source(self) -> None:
        self.copy_path(self._current_source_path())

    def _show_error(self, error: Exception | str) -> None:
        self.status_var.set(f"错误：{error}")
        messagebox.showerror("轨迹 / Direction 实验", str(error), parent=self)

    def close(self) -> None:
        self.closing = True; self._deactivate_mousewheel(); self.unbind_class(self._wheel_tag, "<MouseWheel>"); self.stop_play(); self.worker.close()

