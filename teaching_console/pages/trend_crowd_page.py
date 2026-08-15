"""Tkinter teaching page for formal occupancy trend and Crowd Index analysis."""
from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from teaching_console.services.trend_crowd_teaching_service import TrendCrowdPacket, TrendCrowdTeachingService
from teaching_console.services.vision_teaching_service import (
    VisionTeachingError,
    VisionTeachingWorker,
    find_example_video,
    load_vision_config,
    teaching_cases,
)


LEVEL_HISTORY = "history"
LEVEL_TREND = "trend"
LEVEL_CROWD = "crowd"


def optional_number(value: object, digits: int = 1, signed: bool = False) -> str:
    if value is None:
        return "历史数据不足，暂不能预测。"
    prefix = "+" if signed else ""
    return f"{float(value):{prefix}.{digits}f}"


class TrendCrowdPage(ttk.Frame):
    """Scrollable display; all model and formal-pipeline work stays in the worker."""

    def __init__(self, master, root_path: Path, open_source, copy_path) -> None:
        super().__init__(master)
        self.root_path = Path(root_path)
        self.open_source = open_source
        self.copy_path = copy_path
        self.config = load_vision_config(self.root_path)
        self.worker = VisionTeachingWorker(TrendCrowdTeachingService(self.root_path))
        self.video = None
        self.cases = teaching_cases(self.root_path)
        self.current_case: tuple[str, str] | None = None
        self.frame_index = 0
        self.level_var = tk.StringVar(value=LEVEL_HISTORY)
        self.status_var = tk.StringVar(value="准备就绪：默认将打开 000318 人数增长案例")
        self.video_var = tk.StringVar(value="尚未选择视频")
        self.model_var = tk.StringVar(value=f"模型：{self.config.model_path.name}（按需加载）")
        self.frame_var = tk.StringVar(value="帧：—")
        self.current_var = tk.StringVar(value="当前人数：—")
        self.trend_var = tk.StringVar(value="趋势预测：尚未累积历史")
        self.index_var = tk.StringVar(value="Crowd Index：—")
        self.teaching_var = tk.StringVar()
        self.seek_var = tk.DoubleVar(value=0)
        self.playing = False
        self.busy = False
        self.closing = False
        self.request_token = 0
        self._image = None
        self._packet: TrendCrowdPacket | None = None
        self._wheel_tag = f"TrendCrowdWheel_{id(self)}"
        self._wheel_targets: list[tk.Misc] = []
        self._build_scroll_container()
        self._build()
        self._register_wheel_targets()
        self.bind_class(self._wheel_tag, "<MouseWheel>", self._on_mousewheel)
        self.bind("<Map>", self._activate_mousewheel, add="+")
        self.bind("<Unmap>", self._deactivate_mousewheel, add="+")
        self._set_teaching_text()
        self.after(40, self._drain_worker)
        self.after(80, self.load_default_case)

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
        ttk.Label(self.body, text="趋势 / Crowd Index 实验", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(self.body, text="真实链路：Track ID → 左右区域人数历史 → 一阶趋势预测 → 空间汇合 → Crowd Index → 人群风险状态。", wraplength=1080).pack(anchor="w", pady=(2, 8))
        controls = ttk.Frame(self.body); controls.pack(fill="x")
        for code, purpose in (("000318", "人数增长"), ("000353", "增长/趋势"), ("000345", "人数下降"), ("000327", "人流")):
            ttk.Button(controls, text=f"{code} {purpose}", command=lambda c=code: self.load_case(c)).pack(side="left", padx=(0, 5))
        ttk.Button(controls, text="选择本地视频", command=self.choose_video).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="重新加载模型", command=self.reload_models).pack(side="left", padx=5)
        ttk.Label(controls, textvariable=self.status_var).pack(side="right")
        ttk.Label(self.body, textvariable=self.video_var, foreground="#555555", wraplength=1080).pack(anchor="w", pady=(5, 0))
        ttk.Label(self.body, textvariable=self.model_var, foreground="#555555").pack(anchor="w")

        body = ttk.Panedwindow(self.body, orient="horizontal"); body.pack(fill="both", expand=True, pady=(10, 0))
        viewer, details = ttk.Frame(body), ttk.Frame(body)
        body.add(viewer, weight=3); body.add(details, weight=2)
        self._build_viewer(viewer)
        self._build_details(details)

        levels = ttk.LabelFrame(self.body, text="教学层级", padding=8); levels.pack(fill="x", pady=(8, 0))
        for level, label in ((LEVEL_HISTORY, "人数历史"), (LEVEL_TREND, "趋势预测"), (LEVEL_CROWD, "Crowd Index")):
            ttk.Radiobutton(levels, text=label, variable=self.level_var, value=level, command=self.change_level).pack(side="left", padx=(0, 18))
        ttk.Label(levels, text="跳转或回退后，趋势历史需要重新积累。", foreground="#665500").pack(side="left")

        graph_box = ttk.LabelFrame(self.body, text="人数历史与预测图", padding=6); graph_box.pack(fill="x", pady=(8, 0))
        self.graph = tk.Canvas(graph_box, height=230, background="white", highlightthickness=1, highlightbackground="#bbbbbb")
        self.graph.pack(fill="x", expand=True)
        self.graph.bind("<Configure>", lambda _event: self._draw_graph())
        self.index_box = ttk.LabelFrame(self.body, text="Crowd Index 分解", padding=8)
        ttk.Label(self.index_box, textvariable=self.index_var, justify="left", wraplength=1050).pack(anchor="w")

        nav = ttk.Frame(self.body); nav.pack(fill="x", pady=(8, 0))
        ttk.Button(nav, text="上一帧", command=self.previous_frame).pack(side="left")
        self.play_button = ttk.Button(nav, text="播放", command=self.toggle_play); self.play_button.pack(side="left", padx=5)
        ttk.Button(nav, text="下一帧", command=self.next_frame).pack(side="left")
        self.seek = ttk.Scale(nav, variable=self.seek_var, from_=0, to=1); self.seek.pack(side="left", fill="x", expand=True, padx=16)
        self.seek.bind("<ButtonRelease-1>", self.seek_release)
        ttk.Label(nav, textvariable=self.frame_var, width=25).pack(side="right")

    def _build_viewer(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="真实视频画面", padding=6); box.pack(fill="both", expand=True, padx=(0, 6))
        self.image_label = ttk.Label(box, text="正在准备示例视频…", anchor="center")
        self.image_label.pack(fill="both", expand=True)

    def _build_details(self, parent) -> None:
        current = ttk.LabelFrame(parent, text="当前状态数据", padding=8); current.pack(fill="x", padx=(6, 0))
        ttk.Label(current, textvariable=self.current_var, justify="left", wraplength=400).pack(anchor="w")
        self.trend_box = ttk.LabelFrame(parent, text="最近 15 秒趋势预测", padding=8)
        ttk.Label(self.trend_box, textvariable=self.trend_var, justify="left", wraplength=400).pack(anchor="w")
        self.teaching_box = ttk.LabelFrame(parent, text="课堂观察", padding=8); self.teaching_box.pack(fill="x", padx=(6, 0), pady=(8, 0))
        ttk.Label(self.teaching_box, textvariable=self.teaching_var, justify="left", wraplength=400).pack(anchor="w")
        ttk.Label(self.teaching_box, text="Crowd Index 是人为设计的无量纲综合指标，不是神经网络 confidence，也不是事故或拥挤发生概率。", justify="left", wraplength=400).pack(anchor="w", pady=(6, 0))

    def load_default_case(self) -> None:
        self.load_case("000318")

    def load_case(self, code: str) -> None:
        item = next(((item_code, purpose, path) for item_code, purpose, path in self.cases if item_code == code), None)
        if item is None:
            self._show_error(f"未找到教学案例 {code} 的原始输入视频。")
            return
        self.current_case = (item[0], item[1]); self.load_video(item[2])

    def choose_video(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="选择本地视频", initialdir=str(self.root_path), filetypes=(("视频文件", "*.mp4 *.avi *.mov *.mkv"), ("所有文件", "*.*")))
        if path:
            self.current_case = None; self.load_video(Path(path))

    def load_video(self, path: Path) -> None:
        self.stop_play(); self._submit("open_video", path); self.status_var.set("正在后台打开视频…")

    def reload_models(self) -> None:
        self.stop_play(); self._submit("reload_models"); self.status_var.set("已释放模型、追踪和趋势状态；下次分析将重新积累历史")

    def change_level(self) -> None:
        self._set_teaching_text(); self._update_panels(); self._draw_graph()

    def previous_frame(self) -> None:
        self.stop_play(); self._request_frame(max(0, self.frame_index - 1), sequential=False)

    def next_frame(self) -> None:
        self._request_frame(self.frame_index + 1, sequential=True)

    def toggle_play(self) -> None:
        if self.playing:
            self.stop_play(); return
        if self.video is None:
            return
        self.playing = True; self.play_button.configure(text="暂停")
        self._request_frame(self.frame_index + 1, sequential=True)

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
        self._submit("read_trend_frame", index, sequential)
        self.status_var.set(f"正在分析第 {index + 1} 帧…")

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
            self.video_var.set(f"{case_text}  | 视频：{value.path} | {value.width}×{value.height} | {value.fps:.2f} FPS | {value.total_frames} 帧")
            self.status_var.set("视频已打开；连续播放或连续下一帧才能积累趋势历史")
            self._request_frame(0, sequential=False)
        elif operation == "read_trend_frame":
            self._render_packet(value)
        elif operation == "reload_models":
            self.model_var.set(f"模型：{self.config.model_path.name}（已释放，按需重新加载）")

    def _render_packet(self, packet: TrendCrowdPacket) -> None:
        self._packet = packet; frame = packet.frame; self.frame_index = frame.frame_index; self.seek_var.set(frame.frame_index)
        self.frame_var.set(f"帧：{frame.frame_index + 1}/{frame.video.total_frames} | {frame.seconds:.2f} 秒")
        self._render_image(frame.frame_bgr)
        trend = packet.trend
        self.current_var.set(f"当前人数：{trend.total_people}\n左侧：{trend.left_people}  | 右侧：{trend.right_people}\n当前人数只是此刻占用，不代表接下来一定安全或危险。")
        self._set_trend_text(packet)
        self._set_index_text(packet)
        self._update_panels(); self._draw_graph()
        self.model_var.set(f"模型：{self.config.model_path.name} | person-only | conf={self.config.confidence:.2f}")
        reset_note = "；跳转后已重建追踪与趋势历史" if packet.reset else ""
        self.status_var.set(f"已处理 {len(frame.rows)} 人，历史快照 {len(packet.history)} 个{reset_note}")
        if self.playing:
            if frame.frame_index + 1 >= frame.video.total_frames:
                self.stop_play()
            else:
                self.after(120, lambda: self._request_frame(frame.frame_index + 1, sequential=True))

    def _set_trend_text(self, packet: TrendCrowdPacket) -> None:
        forecast = packet.forecast
        if not forecast.get("prediction_valid"):
            self.trend_var.set("历史数据不足，暂不能预测。\n正式 Predictor 需要足够的快照样本与时间跨度；不会生成假值。")
            return
        predictions = forecast["predicted_people"]
        slope = optional_number(forecast.get("prediction_slope"), 3, signed=True)
        direction = "人数总体增加" if float(forecast["prediction_slope"]) > 0 else ("人数总体减少" if float(forecast["prediction_slope"]) < 0 else "人数整体较稳定")
        self.trend_var.set(
            f"用于拟合的数据窗口：最近约 {self.worker.service.trend_config.prediction.get('window_seconds', 15)} 秒\n"
            f"有效样本：{len(packet.history)}\nprediction_slope：{slope} 人/秒（{direction}）\n"
            f"+10s：{optional_number(predictions.get(10), 1)} 人\n+20s：{optional_number(predictions.get(20), 1)} 人\n+30s：{optional_number(predictions.get(30), 1)} 人\n"
            "这是短期人数趋势拟合，不是事故概率模型；预测是否准确需由未来人工 Ground Truth 验证。"
        )

    def _set_index_text(self, packet: TrendCrowdPacket) -> None:
        metrics = packet.crowd_metrics; config = self.worker.service.trend_config.crowd_index; flow = packet.flow_metrics
        eta = flow.get("convergence_eta")
        self.index_var.set(
            f"Density（现在人有多密）：{float(metrics['density_score']):.2f}  | 权重 {float(config['weight_density']):.2f}\n"
            f"Growth（最近人数增长有多快）：{float(metrics['growth_score']):.2f}  | 权重 {float(config['weight_growth']):.2f}\n"
            f"Convergence（人流是否空间汇合）：{float(metrics['conflict_score']):.2f}  | 权重 {float(config['weight_conflict']):.2f}\n"
            f"正式 FlowRiskAnalyzer convergence_score：{float(flow['convergence_score']):.2f}"
            f"{'，ETA ' + str(eta) + ' s' if eta is not None else ''}\n"
            f"Crowd Index = {float(metrics['index']):.2f}  →  RiskEngine：{packet.base_risk}\n"
            f"正式主链最终 vision_risk：{packet.risk_state}\n"
            "普通人群风险最高为 CROWD；DANGER 是火警语义，不由本页普通 Crowd Index 链产生。"
        )

    def _update_panels(self) -> None:
        if self.level_var.get() == LEVEL_HISTORY:
            self.trend_box.pack_forget(); self.index_box.pack_forget()
        elif self.level_var.get() == LEVEL_TREND:
            self.index_box.pack_forget(); self.trend_box.pack(fill="x", padx=(6, 0), pady=(8, 0), before=self.teaching_box)
        else:
            self.trend_box.pack(fill="x", padx=(6, 0), pady=(8, 0), before=self.teaching_box); self.index_box.pack(fill="x", pady=(8, 0))

    def _draw_graph(self) -> None:
        canvas = self.graph; canvas.delete("all")
        width, height = max(canvas.winfo_width(), 420), max(canvas.winfo_height(), 230)
        left, top, right, bottom = 48, 18, width - 18, height - 34
        canvas.create_line(left, top, left, bottom, fill="#666666")
        canvas.create_line(left, bottom, right, bottom, fill="#666666")
        canvas.create_text(8, top, text="人数", anchor="nw", fill="#444444")
        canvas.create_text(right, bottom + 18, text="时间", anchor="e", fill="#444444")
        if self._packet is None or not self._packet.history:
            canvas.create_text(width // 2, height // 2, text="连续播放后将显示正式 PeopleFlow 历史", fill="#666666")
            return
        history = self._packet.history; times = [item[0] for item in history]; totals = [item[1] + item[2] for item in history]
        prediction_values = self._packet.forecast.get("predicted_people", {}) if self._packet.forecast.get("prediction_valid") and self.level_var.get() != LEVEL_HISTORY else {}
        horizon_end = times[-1] + max((int(horizon) for horizon, value in prediction_values.items() if value is not None), default=0)
        predicted_maximum = max((float(value) for value in prediction_values.values() if value is not None), default=0.0)
        start, end = times[0], max(times[-1], horizon_end, times[0] + 1.0); maximum = max(1, max(totals), predicted_maximum)
        def point(timestamp, people):
            x = left + (float(timestamp) - start) / (end - start) * (right - left)
            y = bottom - float(people) / maximum * (bottom - top)
            return x, y
        points = [point(timestamp, people) for timestamp, people in zip(times, totals)]
        if len(points) > 1:
            canvas.create_line(*[value for item in points for value in item], fill="#2867a8", width=2)
        for x, y in points:
            canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#2867a8", outline="")
        canvas.create_text(left, bottom + 18, text=f"{times[0]:.0f}s", anchor="w", fill="#555555")
        canvas.create_text(right, bottom + 18, text=f"{times[-1]:.0f}s", anchor="e", fill="#555555")
        if self.level_var.get() != LEVEL_HISTORY and self._packet.forecast.get("prediction_valid"):
            predicted = self._packet.forecast["predicted_people"]
            current = totals[-1]; previous = point(times[-1], current)
            for horizon in (10, 20, 30):
                value = predicted.get(horizon)
                if value is None:
                    continue
                future = point(times[-1] + horizon, value)
                canvas.create_line(*previous, *future, fill="#b56d20", dash=(4, 3), width=2)
                canvas.create_text(future[0], max(top + 8, future[1] - 10), text=f"+{horizon}", fill="#b56d20")
                previous = future

    def _render_image(self, frame_bgr) -> None:
        try:
            from PIL import Image, ImageTk
            image = Image.fromarray(frame_bgr[:, :, ::-1]); image.thumbnail((640, 420))
            self._image = ImageTk.PhotoImage(image); self.image_label.configure(image=self._image, text="")
        except Exception as error:
            self.image_label.configure(image="", text=f"无法显示画面：{error}")

    def _set_teaching_text(self) -> None:
        level = self.level_var.get()
        if level == LEVEL_HISTORY:
            self.teaching_var.set("先看当前人数与最近约 30 秒人数历史。只看当前人数，不能说明接下来会增加还是减少。")
        elif level == LEVEL_TREND:
            self.teaching_var.set("系统使用最近一段时间的占用快照做一阶拟合 N(t) ≈ a·t + b，其中 a 是 prediction_slope；不是最后两帧相减。")
        else:
            self.teaching_var.set("Crowd Index 综合 density、growth、convergence。Convergence 来自正式 FlowRiskAnalyzer 的空间汇合分数，不是旧 direction_conflict。")

    def _show_error(self, error: Exception | str) -> None:
        self.status_var.set(f"错误：{error}")
        messagebox.showerror("趋势 / Crowd Index 实验", str(error), parent=self)

    def close(self) -> None:
        self.closing = True; self._deactivate_mousewheel(); self.unbind_class(self._wheel_tag, "<MouseWheel>"); self.stop_play(); self.worker.close()

