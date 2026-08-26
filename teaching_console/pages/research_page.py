"""Count-only Ground Truth page."""
from __future__ import annotations
import queue
import threading
from datetime import date
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from teaching_console.services.research_count_service import ResearchCountService
from teaching_console.services.research_prediction_service import HORIZONS, ResearchPredictionService, annotation_horizons
from teaching_console.services.research_prediction_workflow import select_frozen_prediction_anchor, validation_cards
from teaching_console.services.research_record_exporter import ResearchRecordExporter
from teaching_console.services.research_store import ResearchStore
from teaching_console.services.research_vision_service import ResearchVisionService
from teaching_console.services.vision_teaching_service import VisionTeachingWorker
from teaching_console.runtime_paths import ensure_writable_data_root
from teaching_console.ui_zoom import CONTROL_MASK, scaled_value


TYPE_LABELS = {"teaching": "教学练习", "formal": "正式研究"}

def format_prediction_slope(value):
    """Render a prediction slope for the UI without changing stored data."""
    return "暂无数据" if value is None else f"{float(value):+.3f}"


def format_prediction_value(value):
    """Render a predicted people count for the UI without changing stored data."""
    return "暂无数据" if value is None else f"{float(value):.1f}"


def format_prediction_error(value):
    """Render one prediction absolute error for the UI."""
    return "暂无数据" if value is None else f"{float(value):.1f}"


def format_prediction_mae(value):
    """Render an aggregate prediction MAE for the UI."""
    return "暂无数据" if value is None else f"{float(value):.2f}"


def experiment_list_rows(store):
    """UI-only projection; the UUID remains Treeview item data, not user text."""
    rows = []
    for experiment in store.list_experiments():
        completed, total = store.progress(experiment["id"])
        rows.append({"id": experiment["id"], "name": experiment["name"], "type": TYPE_LABELS.get(experiment["experiment_type"], experiment["experiment_type"]), "video": Path(experiment["video_path"]).name, "progress": f"{completed} / {total}" if total else "未生成", "created_at": experiment["created_at"].replace("T", " ")})
    return rows


def prediction_target(anchor_time_seconds: float, horizon_seconds: int, fps: float) -> tuple[float, int]:
    target_time = float(anchor_time_seconds) + int(horizon_seconds)
    return target_time, int(round(target_time * fps))


def preview_prediction_error(prediction, entered_count: str) -> str:
    """Display-only feedback; stored floats remain untouched until Save."""
    try:
        actual = int(entered_count.strip())
        if actual < 0 or str(actual) != entered_count.strip() or prediction is None:
            raise ValueError
        return f"误差：{format_prediction_error(abs(float(prediction) - actual))} 人（保存后记录）"
    except (TypeError, ValueError):
        return "误差：自动计算"


BASE_VIDEO_SIZE = (640, 420)


class ResearchPage(ttk.Frame):
    def __init__(self, master, root_path: Path) -> None:
        super().__init__(master)
        self.root_path = root_path; self.data_root = ensure_writable_data_root(root_path); self.store = ResearchStore(self.data_root); self.counts = ResearchCountService(self.store); self.predictions = ResearchPredictionService(self.store)
        self.worker = VisionTeachingWorker(ResearchVisionService(root_path)); self._zoom_factor=1.0; self._count_frame_bgr=None; self._prediction_frame_bgr=None; self.experiment = None; self.video = None; self.tasks=[]; self.index=0; self.token=0; self.busy=False; self.closing=False; self._prediction_target=None; self._prediction_photo=None; self._detect_id=None; self._next_after_detect=None; self.mode=tk.StringVar(value="count"); self.pred_index=0; self.pred_rows=[]; self._auto_analysis_pending=False; self.pred_playing=False; self._prediction_play_after=None
        self.gt=tk.StringVar(); self.note=tk.StringVar(); self.status=tk.StringVar(value="请新建或打开实验"); self.meta=tk.StringVar(); self.point=tk.StringVar(); self.result=tk.StringVar(); self.metrics=tk.StringVar(); self.jump=tk.StringVar()
        self._scroll(); self._build(); self.after(40,self._drain)
    def _scroll(self):
        self.canvas=tk.Canvas(self,highlightthickness=0); self.bar=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview); self.canvas.configure(yscrollcommand=self.bar.set); self.canvas.pack(side='left',fill='both',expand=True); self.bar.pack(side='right',fill='y'); self.body=ttk.Frame(self.canvas,padding=12); self.window=self.canvas.create_window((0,0),window=self.body,anchor='nw'); self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all'))); self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.window,width=e.width)); self.bind('<Enter>',lambda e:self.canvas.bind_all('<MouseWheel>',self._wheel,add='+')); self.bind('<Leave>',lambda e:self.canvas.unbind_all('<MouseWheel>'))
    def _wheel(self,e):
        if e.state & CONTROL_MASK:return None
        self.canvas.yview_scroll(-int(e.delta/120 or (1 if e.delta<0 else -1)),'units'); return 'break'
    def _build(self):
        ttk.Label(self.body,text='AI人数实验｜研究记录',font=('Segoe UI',16,'bold')).pack(anchor='w');ttk.Label(self.body,text='跟着步骤做实验：创建实验 → 观察画面 → 记录人工真实答案 → 查看 AI 结果 → 分析误差 → 生成研究资料。',wraplength=1050).pack(anchor='w'); modes=ttk.Frame(self.body);modes.pack(anchor='w',pady=(4,0));ttk.Radiobutton(modes,text='人数 Ground Truth',variable=self.mode,value='count',command=self.set_mode).pack(side='left');ttk.Radiobutton(modes,text='预测 Ground Truth',variable=self.mode,value='prediction',command=self.set_mode).pack(side='left',padx=12);ttk.Label(self.body,text='Ground Truth（人工真实答案）：先自己观察原始画面并记录真实人数，用来检查 AI 是否准确。',wraplength=1050).pack(anchor='w');self.count_area=ttk.Frame(self.body);self.count_area.pack(fill='both',expand=True)
        top=ttk.Frame(self.count_area);top.pack(fill='x',pady=8);ttk.Button(top,text='开始新实验',command=self.new).pack(side='left');ttk.Button(top,text='打开研究记录',command=self.open).pack(side='left',padx=5);ttk.Button(top,text='填写研究计划与总结',command=self.edit_record).pack(side='left');ttk.Button(top,text='生成研究资料',command=self.export).pack(side='left',padx=5);ttk.Label(top,textvariable=self.status).pack(side='right')
        ttk.Label(self.count_area,textvariable=self.meta,wraplength=1050).pack(anchor='w'); body=ttk.Panedwindow(self.count_area,orient='horizontal');body.pack(fill='both',expand=True,pady=8);left,right=ttk.Frame(body),ttk.Frame(body);body.add(left,weight=3);body.add(right,weight=2);self.image=ttk.Label(left,text='选择实验后显示原始视频帧',anchor='center');self.image.pack(fill='both',expand=True); self._right(right)
        bottom=ttk.LabelFrame(self.count_area,text='研究统计',padding=8);bottom.pack(fill='x');ttk.Label(bottom,textvariable=self.metrics).pack(anchor='w'); key=ttk.Frame(bottom);key.pack(anchor='w',pady=5);ttk.Entry(key,textvariable=self.jump,width=10).pack(side='left');ttk.Button(key,text='显示该时刻原始画面（暂停）',command=self.jump_time).pack(side='left',padx=4);ttk.Button(key,text='添加当前时刻为关键样本',command=self.key).pack(side='left')
        self._build_prediction()

    def _build_prediction(self):
        self.pred_area = ttk.Frame(self.body, padding=(0, 8))
        self.pred_status, self.pred_info, self.pred_metrics = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.pred_video_info = tk.StringVar(value="当前视频：尚未选择实验视频")
        self.pred_current_time = tk.DoubleVar(value=0.0)
        self.pred_start_time = tk.DoubleVar(value=0.0)
        self.pred_time_label = tk.StringVar(value="当前时间：--")
        self.pred_start_label = tk.StringVar(value="预测起点：尚未设置")
        self.pred_anchor_choice = tk.StringVar()
        self._prediction_anchor_choices = {}
        self.pred_gt = {slot: tk.StringVar() for slot in HORIZONS}
        self.pred_ai = {slot: tk.StringVar(value="AI预测人数：暂无数据") for slot in HORIZONS}
        self.pred_title = {slot: tk.StringVar(value=f"+{slot} 秒预测验证") for slot in HORIZONS}
        self.pred_target_text = {slot: tk.StringVar(value="目标时间：--") for slot in HORIZONS}
        self.pred_rows_by_slot, self.pred_entries, self.pred_view_buttons, self.pred_reference_buttons = {}, {}, {}, {}
        self.pred_error = {slot: tk.StringVar(value="误差：自动计算") for slot in HORIZONS}
        for slot in HORIZONS:
            self.pred_gt[slot].trace_add("write", lambda *_args, current_slot=slot: self._preview_prediction_error(current_slot))
        ttk.Label(self.pred_area, text="预测 Ground Truth", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(self.pred_area, text="按真实科研流程操作：选择实验视频 → 观察原始画面 → 设置预测起点 → 读取已冻结的 AI 预测 → 查看未来画面 → 填写真实人数。", wraplength=1000).pack(anchor="w")
        source = ttk.LabelFrame(self.pred_area, text="第 1 步：选择实验视频", padding=6)
        source.pack(fill="x", pady=(6, 4))
        ttk.Button(source, text="新建实验并选择视频", command=self.new).pack(side="left")
        ttk.Button(source, text="打开已有实验视频", command=self.open).pack(side="left", padx=5)
        ttk.Label(source, textvariable=self.pred_video_info, wraplength=760).pack(side="left", padx=10)
        player = ttk.LabelFrame(self.pred_area, text="第 2 步：观察原始视频并选择预测起点", padding=6)
        player.pack(fill="both", expand=True, pady=4)
        controls = ttk.Frame(player)
        controls.pack(fill="x", pady=(0, 4))
        ttk.Button(controls, text="播放", command=self.play_prediction_video).pack(side="left")
        ttk.Button(controls, text="暂停", command=self.pause_prediction_video).pack(side="left", padx=4)
        ttk.Label(controls, textvariable=self.pred_time_label).pack(side="left", padx=10)
        ttk.Button(controls, text="设置预测起点", command=self.set_prediction_start).pack(side="left")
        ttk.Label(controls, textvariable=self.pred_start_label).pack(side="left", padx=8)
        self.pred_timeline = ttk.Scale(player, from_=0, to=1, variable=self.pred_current_time, command=self.seek_prediction_video)
        self.pred_timeline.pack(fill="x", pady=(0, 4))
        self.pred_view_label = tk.StringVar(value="当前查看：请先选择实验视频")
        ttk.Label(player, textvariable=self.pred_view_label).pack(anchor="w")
        self.pred_image = ttk.Label(player, text="原始视频画面会显示在这里（不绘制 YOLO 框）。", anchor="center")
        self.pred_image.pack(fill="both", expand=True)
        setup = ttk.LabelFrame(self.pred_area, text="第 3 步：读取已有 AI 预测", padding=6)
        setup.pack(fill="x", pady=4)
        ttk.Label(setup, text="可用预测起点：").pack(side="left")
        self.pred_anchor_box = ttk.Combobox(setup, textvariable=self.pred_anchor_choice, state="readonly", width=32)
        self.pred_anchor_box.pack(side="left")
        self.pred_anchor_box.bind("<<ComboboxSelected>>", self.choose_prediction_anchor)
        ttk.Button(setup, text="开始预测验证", command=self.begin_prediction_validation).pack(side="left", padx=6)
        ttk.Label(self.pred_area, textvariable=self.pred_status, wraplength=1000).pack(anchor="w", pady=4)
        ttk.Label(self.pred_area, textvariable=self.pred_info, wraplength=1000).pack(anchor="w", pady=6)
        self.pred_form = ttk.Frame(self.pred_area)
        self.pred_form.pack(fill="x")
        for slot in HORIZONS:
            row = ttk.LabelFrame(self.pred_form, text=self.pred_title[slot].get(), padding=6)
            self.pred_rows_by_slot[slot] = row
            row.pack(fill="x", pady=3)
            ttk.Label(row, textvariable=self.pred_ai[slot]).pack(side="left", padx=(0, 16))
            ttk.Label(row, textvariable=self.pred_target_text[slot]).pack(side="left", padx=(0, 12))
            ttk.Label(row, text="真实人数：").pack(side="left")
            entry = ttk.Entry(row, textvariable=self.pred_gt[slot], width=10)
            entry.pack(side="left")
            self.pred_entries[slot] = entry
            view = ttk.Button(row, text="查看原始画面", command=lambda current_slot=slot: self.view_prediction_target(current_slot))
            view.pack(side="left", padx=5)
            self.pred_view_buttons[slot] = view
            reference = ttk.Button(row, text="引用已有人数 Ground Truth", command=lambda current_slot=slot: self.reference_count_gt(current_slot))
            reference.pack(side="left")
            self.pred_reference_buttons[slot] = reference
            ttk.Label(row, textvariable=self.pred_error[slot]).pack(side="left", padx=8)
        nav = ttk.Frame(self.pred_area)
        nav.pack(anchor="w", pady=6)
        ttk.Button(nav, text="上一个预测点", command=lambda: self.show_prediction(self.pred_index - 1)).pack(side="left")
        ttk.Button(nav, text="保存预测验证", command=self.save_prediction).pack(side="left", padx=4)
        ttk.Button(nav, text="保存并下一个预测点", command=lambda: self.save_prediction(True)).pack(side="left")
        ttk.Button(nav, text="下一个预测点", command=lambda: self.show_prediction(self.pred_index + 1)).pack(side="left", padx=4)
        ttk.Button(nav, text="生成预测研究资料", command=self.export).pack(side="left", padx=12)
        ttk.Label(self.pred_area, textvariable=self.pred_metrics, wraplength=1000).pack(anchor="w")
    def _current_prediction(self):
        return self.pred_rows[self.pred_index] if self.pred_rows else None

    def _actual_horizons(self, annotation=None) -> tuple[int, int, int]:
        return annotation_horizons(annotation or self._current_prediction()) if (annotation or self._current_prediction()) is not None else HORIZONS

    def _actual_horizon(self, slot: int) -> int:
        return dict(zip(HORIZONS, self._actual_horizons()))[slot]

    def _video_duration(self) -> float:
        if self.video is None or not self.video.fps:
            return 0.0
        return max(0.0, self.video.total_frames / self.video.fps)

    def _prediction_cards(self, annotation=None):
        item = annotation or self._current_prediction()
        if item is None:
            return []
        return validation_cards(item, fps=self.video.fps if self.video else 0.0, video_duration_seconds=self._video_duration())

    def _preview_prediction_error(self, slot: int) -> None:
        annotation = self._current_prediction()
        if annotation is not None:
            self.pred_error[slot].set(preview_prediction_error(annotation[f"prediction_{slot}"], self.pred_gt[slot].get()))

    def _set_prediction_card_enabled(self, slot: int, enabled: bool) -> None:
        widgets = (self.pred_entries[slot], self.pred_view_buttons[slot], self.pred_reference_buttons[slot])
        if enabled:
            for widget in widgets:
                if not widget.winfo_manager():
                    widget.pack(side="left", padx=5 if widget is self.pred_view_buttons[slot] else 0)
                widget.state(["!disabled"])
        else:
            for widget in widgets:
                widget.state(["disabled"])
                widget.pack_forget()

    def _reset_prediction_cards(self) -> None:
        for slot in HORIZONS:
            self.pred_title[slot].set(f"+{slot} 秒预测验证")
            self.pred_rows_by_slot[slot].configure(text=self.pred_title[slot].get())
            self.pred_ai[slot].set("AI预测人数：暂无数据")
            self.pred_target_text[slot].set("目标时间：请先设置预测起点")
            self.pred_gt[slot].set("")
            self.pred_error[slot].set("误差：自动计算")
            self._set_prediction_card_enabled(slot, False)

    def _set_prediction_player_time(self, time_seconds: float, description: str) -> None:
        if self.video is None:
            self.pred_status.set("请先选择实验视频。")
            return
        duration = self._video_duration()
        target_time = min(max(0.0, float(time_seconds)), duration)
        frame = min(max(0, int(round(target_time * self.video.fps))), max(0, self.video.total_frames - 1))
        self.pred_current_time.set(target_time)
        self.pred_time_label.set(f"当前时间：{target_time:.2f} s / {duration:.2f} s")
        self.pred_view_label.set(f"当前查看：{description}  |  视频时间：{target_time:.2f} s  |  帧号：{frame}")
        self._prediction_target = ("player", target_time, frame)
        self._send("read_raw", frame)

    def seek_prediction_video(self, value) -> None:
        if self.video is None or self.pred_playing:
            return
        self._set_prediction_player_time(float(value), "原始视频画面")

    def set_prediction_start(self) -> None:
        if self.video is None:
            self.pred_status.set("请先选择实验视频。")
            return
        self.pause_prediction_video()
        selected = float(self.pred_current_time.get())
        self.pred_start_time.set(selected)
        self.pred_start_label.set(f"预测起点：{selected:.2f} s")
        self.pred_status.set("已设置预测起点。请读取该时刻已有的 AI 预测；若无数据，请从下拉列表选择可用起点。")

    def play_prediction_video(self) -> None:
        if self.video is None:
            self.pred_status.set("请先选择实验视频。")
            return
        if self.pred_current_time.get() >= self._video_duration():
            self.pred_current_time.set(0.0)
        self.pred_playing = True
        self._advance_prediction_playback()

    def pause_prediction_video(self) -> None:
        self.pred_playing = False
        if self._prediction_play_after is not None:
            self.after_cancel(self._prediction_play_after)
            self._prediction_play_after = None

    def _advance_prediction_playback(self) -> None:
        if not self.pred_playing or self.video is None:
            return
        current = float(self.pred_current_time.get())
        if current >= self._video_duration():
            self.pause_prediction_video()
            return
        next_time = min(self._video_duration(), current + 1.0 / max(1.0, self.video.fps))
        self._set_prediction_player_time(next_time, "原始视频播放")

    def choose_prediction_anchor(self, _event=None) -> None:
        index = self._prediction_anchor_choices.get(self.pred_anchor_choice.get())
        if index is None:
            return
        annotation = self.pred_rows[index]
        self.pause_prediction_video()
        self.pred_start_time.set(float(annotation["anchor_time_seconds"]))
        self.pred_start_label.set(f"预测起点：{float(annotation['anchor_time_seconds']):.2f} s")
        self._set_prediction_player_time(float(annotation["anchor_time_seconds"]), "已选择的预测起点原始画面")
        self.pred_status.set("已定位一个有冻结 AI 预测的起点。确认原始画面后，点击“开始预测验证”。")

    def begin_prediction_validation(self) -> None:
        self.pause_prediction_video()
        if self.experiment is None or self.video is None:
            self.pred_status.set("请先选择实验视频。")
            return
        annotation = select_frozen_prediction_anchor(
            self.pred_rows,
            selected_time_seconds=self.pred_start_time.get(),
            video_duration_seconds=self._video_duration(),
        )
        if annotation is None:
            self._reset_prediction_cards()
            self.pred_info.set("")
            self.pred_status.set("当前时间没有有效预测数据。请重新选择预测起点，或从“可用预测起点”列表中选择。")
            return
        self.pred_index = self.pred_rows.index(annotation)
        self.show_prediction(self.pred_index)

    def set_mode(self):
        if self.mode.get() == "prediction":
            self.count_area.pack_forget()
            self.pred_area.pack(fill="both", expand=True)
            self.refresh_prediction()
            if self.pred_rows and self.video is not None:
                self.choose_prediction_anchor()
        else:
            self.pause_prediction_video()
            self.pred_area.pack_forget()
            self._prediction_target = None
            self.count_area.pack(fill="both", expand=True)

    def refresh_prediction(self):
        self._reset_prediction_cards()
        if not self.experiment:
            self.pred_video_info.set("当前视频：尚未选择实验视频")
            self.pred_anchor_box.configure(values=())
            self.pred_status.set("请先新建实验并选择视频，或打开已有实验。")
            self.pred_info.set("")
            return
        path = Path(self.experiment["video_path"])
        duration = self._video_duration()
        self.pred_video_info.set(f"当前视频：{path.name}  |  时长：{duration:.2f} 秒" if self.video else f"当前视频：{path.name}（正在读取视频信息）")
        if self.video:
            self.pred_timeline.configure(to=max(0.01, duration))
            self.pred_time_label.set(f"当前时间：{float(self.pred_current_time.get()):.2f} s / {duration:.2f} s")
        self.pred_rows = self.store.prediction_annotations(self.experiment["id"])
        metrics = self.predictions.prediction_metrics(self.experiment["id"])
        horizons = self._actual_horizons(self.pred_rows[0]) if self.pred_rows else HORIZONS
        summaries = "  | ".join(f"+{actual}：{metrics[f'samples_{slot}']}，MAE {format_prediction_mae(metrics[f'mae_{slot}'])} 人" for slot, actual in zip(HORIZONS, horizons))
        self.pred_metrics.set(f"预测实验点：{metrics['prediction_anchor_count']}  完整验证：{metrics['completed_prediction_count']} / {metrics['prediction_anchor_count']}  | {summaries}")
        self._prediction_anchor_choices = {
            f"{float(row['anchor_time_seconds']):.2f} s（系统人数 {row['current_system_count']}）": index
            for index, row in enumerate(self.pred_rows)
        }
        choices = tuple(self._prediction_anchor_choices)
        self.pred_anchor_box.configure(values=choices)
        if not self.pred_rows:
            self.pred_info.set("")
            self.pred_status.set("当前视频没有已准备好的预测数据。请选择另一个有预测记录的视频或预测起点。")
        elif self.pred_anchor_choice.get() not in self._prediction_anchor_choices:
            self.pred_anchor_choice.set(choices[0])
            if self.mode.get() == "prediction":
                self.choose_prediction_anchor()

    def show_prediction(self, index):
        if not self.pred_rows or self.video is None:
            return
        self.pred_index = max(0, min(index, len(self.pred_rows) - 1))
        annotation = self.pred_rows[self.pred_index]
        self.pred_start_time.set(float(annotation["anchor_time_seconds"]))
        self.pred_start_label.set(f"预测起点：{float(annotation['anchor_time_seconds']):.2f} s")
        done = all(annotation[f"gt_{slot}"] is not None for slot in HORIZONS)
        self.pred_status.set(f"预测验证：{self.pred_index + 1} / {len(self.pred_rows)}  {'✓ 已完成' if done else '○ 未完成'}。先查看未来原始画面，再填写真实人数。")
        labels = "  ".join(f"+{card['horizon_seconds']}：{format_prediction_value(card['prediction'])} 人" for card in self._prediction_cards(annotation) if card["available"])
        self.pred_info.set(f"预测起点：{annotation['anchor_time_seconds']:.1f} s  | 当时系统人数：{annotation['current_system_count']}  | 趋势斜率：{format_prediction_slope(annotation['prediction_slope'])} 人/秒\n这些 AI 预测值在起点产生并冻结保存，不会在本页重新计算。\n{labels}")
        for card in self._prediction_cards(annotation):
            slot = int(card["slot"])
            horizon = int(card["horizon_seconds"])
            if card["available"]:
                self.pred_title[slot].set(f"+{horizon} 秒预测验证")
                self.pred_ai[slot].set(f"AI预测人数：{format_prediction_value(card['prediction'])} 人")
                self.pred_target_text[slot].set(f"目标时间：{float(card['target_time_seconds']):.2f} s")
                self._set_prediction_card_enabled(slot, True)
                self.pred_gt[slot].set("" if annotation[f"gt_{slot}"] is None else str(annotation[f"gt_{slot}"]))
                self.pred_error[slot].set(preview_prediction_error(card["prediction"], self.pred_gt[slot].get()) if annotation[f"gt_{slot}"] is None else f"误差：{format_prediction_error(annotation[f'error_{slot}'])} 人")
            else:
                self.pred_title[slot].set(f"+{horizon} 秒：无法验证")
                self.pred_ai[slot].set("AI预测人数：暂无数据")
                self.pred_target_text[slot].set(f"无法验证：目标 {float(card['target_time_seconds']):.2f} s 超过视频长度")
                self.pred_gt[slot].set("")
                self.pred_error[slot].set("无需填写")
                self._set_prediction_card_enabled(slot, False)
            self.pred_rows_by_slot[slot].configure(text=self.pred_title[slot].get())
        self._set_prediction_player_time(float(annotation["anchor_time_seconds"]), "预测起点原始画面")

    def view_prediction_target(self, slot):
        if not self.pred_rows or self.video is None:
            self.pred_status.set("请先选择实验视频并开始预测验证。")
            return
        card = next((item for item in self._prediction_cards() if item["slot"] == slot), None)
        if card is None or not card["available"]:
            self.pred_status.set("该预测目标超过视频长度，无法验证。")
            return
        self.pause_prediction_video()
        horizon = int(card["horizon_seconds"])
        self._set_prediction_player_time(float(card["target_time_seconds"]), f"+{horizon} 秒 Ground Truth")
        self.pred_status.set("请观察原始画面，人工记录该时刻真实人数。AI 预测值已固定，不会影响原始画面。")

    def reference_count_gt(self, slot):
        if not self.pred_rows:
            return
        annotation = self.pred_rows[self.pred_index]
        value = self.predictions.apply_existing_count_gt(annotation["id"], slot, self._actual_horizon(slot))
        if value is None:
            messagebox.showinfo("预测 Ground Truth", "该时刻没有可引用的人工 Ground Truth。", parent=self)
        else:
            self.pred_gt[slot].set(str(value))
            self.refresh_prediction()
            self.show_prediction(self.pred_index)

    def save_prediction(self, next=False):
        if not self.pred_rows:
            self.pred_status.set("请先选择预测起点并开始预测验证。")
            return
        annotation = self.pred_rows[self.pred_index]
        available_slots = {int(card["slot"]) for card in self._prediction_cards(annotation) if card["available"]}
        try:
            for slot in HORIZONS:
                value = self.pred_gt[slot].get().strip()
                if slot in available_slots and value:
                    self.predictions.save_prediction_gt(annotation["id"], slot, int(value))
        except (ValueError, TypeError):
            messagebox.showwarning("输入错误", "人工真实人数必须是非负整数。", parent=self)
            return
        self.store.log_activity(self.experiment["id"], "save_prediction_ground_truth", f"保存 {float(annotation['anchor_time_seconds']):.1f} 秒预测验证")
        self.refresh_prediction()
        self.show_prediction(self.pred_index + 1 if next else self.pred_index)
    def _right(self,p):
        ttk.Label(p,text='当前实验点',font=('Segoe UI',12,'bold')).pack(anchor='w');ttk.Label(p,textvariable=self.point).pack(anchor='w');ttk.Label(p,textvariable=self.result,wraplength=380).pack(anchor='w',pady=5);ttk.Label(p,text='人工真实人数：').pack(anchor='w');ttk.Entry(p,textvariable=self.gt,width=12).pack(anchor='w');ttk.Label(p,text='备注：').pack(anchor='w');ttk.Entry(p,textvariable=self.note,width=38).pack(anchor='w');buttons=ttk.Frame(p);buttons.pack(anchor='w',pady=8);ttk.Button(buttons,text='上一实验点',command=lambda:self.show(self.index-1)).pack(side='left');ttk.Button(buttons,text='保存',command=self.save).pack(side='left',padx=3);ttk.Button(buttons,text='保存并下一个',command=lambda:self.save(True)).pack(side='left');ttk.Button(buttons,text='下一实验点',command=lambda:self.show(self.index+1)).pack(side='left',padx=3)
    def edit_record(self):
        if not self.experiment:
            messagebox.showinfo('研究记录', '请先创建或打开一个实验。', parent=self); return
        fields = (
            ('purpose', '实验目的', '这次想研究什么？'),
            ('participants', '参与学生', '哪些同学参加？'),
            ('experiment_date', '实验日期', '实验在哪一天进行？'),
            ('experiment_scene', '实验场景', '在哪里、什么情况下拍摄？'),
            ('findings', '我的发现', '实验中 AI 哪里做得不好？'),
            ('cause_analysis', '为什么会这样？', '你认为造成这种结果的原因是什么？'),
            ('next_improvement', '下一步怎么改进？', '如果继续研究，你准备怎样帮助 AI 做得更好？'),
            ('student_reflection', '学生心得', '这次实验你学到了什么？'),
        )
        values = {}
        for key, title, prompt in fields:
            value = simpledialog.askstring(title, prompt, parent=self, initialvalue=self.experiment[key] or '')
            if value is None: return
            values[key] = value.strip()
        self.store.update_experiment_record(self.experiment['id'], **values)
        self.experiment = self.store.get_experiment(self.experiment['id'])
        self.status.set('研究计划与总结已保存，可以生成研究资料。')

    def new(self):
        default_name = f"AI人数实验_{date.today():%Y-%m-%d}"
        name = simpledialog.askstring('开始新实验', '给这次 AI 人数实验取一个名称：', parent=self, initialvalue=default_name)
        if not name:
            return
        video = filedialog.askopenfilename(parent=self, filetypes=(('视频', '*.mp4 *.avi *.mov *.mkv'),))
        if not video:
            return
        eid = self.store.create_experiment(name.strip(), video, 'teaching')
        try:
            duration, fps = self._metadata(Path(video))
            self.counts.generate_tasks(eid, duration, fps)
        except Exception as error:
            messagebox.showerror('无法创建实验', f'无法读取视频信息：{error}', parent=self)
            return
        self._auto_analysis_pending = True
        self.status.set('系统正在自动分析视频，生成 AI 人数结果……')
        self.load(eid)
    def open(self):
        dialog = tk.Toplevel(self); dialog.title("打开已有实验"); dialog.geometry("760x420"); dialog.transient(self.winfo_toplevel()); dialog.grab_set()
        frame = ttk.Frame(dialog, padding=12); frame.pack(fill="both", expand=True)
        rows = experiment_list_rows(self.store)
        if not rows:
            ttk.Label(frame, text="暂无已有实验，请先新建实验。").pack(anchor="w")
            ttk.Button(frame, text="取消", command=dialog.destroy).pack(anchor="e", pady=12)
            return
        columns = ("name", "type", "video", "progress", "created")
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        for key, label, width in (("name", "实验名称", 210), ("type", "实验类型", 100), ("video", "视频", 150), ("progress", "人数标注进度", 105), ("created", "创建时间", 160)):
            tree.heading(key, text=label); tree.column(key, width=width, anchor="w")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview); tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True); scrollbar.pack(side="left", fill="y")
        bottom = ttk.Frame(dialog, padding=(12, 0, 12, 12)); bottom.pack(fill="x")
        detail = tk.StringVar(value="选择一个实验后打开。")
        ttk.Label(bottom, textvariable=detail, wraplength=500).pack(side="left")
        def selected():
            item = tree.selection()
            if not item:
                messagebox.showinfo("打开已有实验", "请先选择一个实验。", parent=dialog); return
            self.load(tree.item(item[0], "tags")[0]); dialog.destroy()
        for row in rows:
            tree.insert("", "end", values=(row["name"], row["type"], row["video"], row["progress"], row["created_at"]), tags=(row["id"],))
        tree.bind("<Double-1>", lambda _event: selected())
        ttk.Button(bottom, text="打开", command=selected).pack(side="right")
        ttk.Button(bottom, text="取消", command=dialog.destroy).pack(side="right", padx=5)
    def _metadata(self,path):
        import cv2
        cap=cv2.VideoCapture(str(path));fps=cap.get(cv2.CAP_PROP_FPS) or 0;frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));cap.release()
        if not fps or not frames:raise ValueError('无法读取视频 metadata')
        return frames/fps,fps
    def load(self,eid):
        self.experiment=self.store.get_experiment(eid);self.tasks=self.store.annotations(eid);self.index=0;path=Path(self.experiment['video_path']);self.meta.set(f"实验：{self.experiment['name']}  | 类型：{self.experiment['experiment_type']}  | 视频：{path}")
        self.store.log_activity(eid, 'open_experiment', f"打开实验：{self.experiment['name']}")
        if not path.is_file():self.status.set('原始视频文件不存在；数据库内容仍可查看');self.refresh_prediction();return
        self.store.log_activity(eid, 'view_video', f"查看测试视频：{path.name}")
        self._send('open_video',path)
    def _send(self,op,*args):self.token+=1;self.busy=True;self.worker.submit(self.token,op,*args)
    def _drain(self):
        if self.closing:return
        while True:
            try:r=self.worker.results.get_nowait()
            except queue.Empty:break
            if r.token!=self.token:continue
            self.busy=False
            if r.error:self.status.set('错误：'+r.error);continue
            if r.operation=='open_video':
                self.video=r.value
                if self._auto_analysis_pending:
                    self._auto_analysis_pending=False
                    samples=[(row['id'], row['frame_index']) for row in self.tasks if row['system_count'] is None]
                    self.status.set(f'系统正在自动分析视频…… 0 / {len(samples)}')
                    self._send('analyze_samples', samples)
                else:
                    self.show(0);self.refresh_prediction()
            elif r.operation=='analyze_samples':
                for annotation_id, system_count in r.value:self.store.update_system_count(annotation_id,system_count)
                self.tasks=self.store.annotations(self.experiment['id']);self.status.set(f'✓ AI分析完成：已生成 {len(r.value)} 个检测结果');self.show(0);self.refresh_prediction()
            else:self.render(r.value)
        self.after(40,self._drain)
    def show(self,i):
        if not self.tasks or self.busy:return
        self.index=max(0,min(i,len(self.tasks)-1));a=self.tasks[self.index];self.gt.set('' if a['ground_truth_count'] is None else str(a['ground_truth_count']));self.note.set(a['note']);self.point.set(f"第 {self.index+1} / {len(self.tasks)} 个  |  时间：{a['video_time_seconds']:.2f} s  | 帧：{a['frame_index']}");self.result.set('正式研究：请先独立填写人工人数。' if self.experiment['experiment_type']=='formal' and a['ground_truth_count'] is None else (f"系统人数：{a['system_count']}；人工人数：{a['ground_truth_count']}；绝对误差：{a['absolute_error']}" if a['system_count'] is not None else ''));self._send('read_raw',a['frame_index']);self.refresh()
    def _show_frame(self, target, frame_bgr, prediction=False):
        try:
            from PIL import Image,ImageTk
            image=Image.fromarray(frame_bgr[:,:,::-1])
            image.thumbnail(tuple(scaled_value(value,self._zoom_factor) for value in BASE_VIDEO_SIZE))
            photo=ImageTk.PhotoImage(image)
            if prediction:self._prediction_photo=photo
            else:self.photo=photo
            target.configure(image=photo,text='')
        except Exception as error:
            target.configure(text=str(error),image='')

    def on_zoom_changed(self, factor):
        self._zoom_factor=factor
        if self.mode.get() == 'prediction' and self._prediction_frame_bgr is not None:
            self._show_frame(self.pred_image,self._prediction_frame_bgr,prediction=True)
        elif self._count_frame_bgr is not None:
            self._show_frame(self.image,self._count_frame_bgr)
        self.after_idle(lambda:self.canvas.configure(scrollregion=self.canvas.bbox('all')))

    def render(self,p):
        prediction = self.mode.get() == 'prediction' and self._prediction_target is not None
        if prediction:
            self._prediction_frame_bgr = p.frame_bgr
            self._show_frame(self.pred_image, p.frame_bgr, prediction=True)
            if self.pred_playing and self.video is not None:
                delay_ms = max(35, int(1000 / max(1.0, self.video.fps)))
                self._prediction_play_after = self.after(delay_ms, self._advance_prediction_playback)
        else:
            self._count_frame_bgr = p.frame_bgr
            self._show_frame(self.image, p.frame_bgr)
    def save(self,next=False):
        try:v=int(self.gt.get());assert v>=0 and str(v)==self.gt.get().strip()
        except:messagebox.showwarning('输入错误','人工真实人数必须是非负整数。',parent=self);return
        a=self.tasks[self.index];self.store.update_ground_truth(self.experiment['id'],a['sample_index'],v,self.note.get());self.tasks=self.store.annotations(self.experiment['id'])
        if next:self.show(self.index+1)
        else:self.refresh()
    def refresh(self):
        m=self.counts.metrics(self.experiment['id']);self.metrics.set(f"任务总数：{m['total_tasks']}  已完成：{m['completed_ground_truth']}  可评价：{m['evaluated_samples']}  MAE：{m['mae'] if m['mae'] is not None else '暂无可统计 Ground Truth 数据'}  最大误差：{m['max_absolute_error']}  完全正确率：{m['exact_match_rate']}")
    def jump_time(self):
        try:
            t = float(self.jump.get())
            if self.video is None or t < 0 or t > self.video.total_frames / self.video.fps:
                raise ValueError
            self._send('read_raw', int(round(t * self.video.fps)))
            self.status.set(f'已暂停在 {t:.2f} 秒原始画面；可添加为关键样本后填写真实人数。')
        except Exception:
            messagebox.showwarning('输入错误', '请输入视频范围内的有效秒数。', parent=self)
    def key(self):
        if not self.video:return
        try:t=float(self.jump.get())
        except:t=self.tasks[self.index]['video_time_seconds'] if self.tasks else 0
        if self.counts.add_key_sample(self.experiment['id'],t,self.video.fps,note='关键样本') is None:messagebox.showinfo('关键样本','该时刻附近已经存在研究样本。',parent=self)
        self.tasks=self.store.annotations(self.experiment['id']);self.refresh()
    def export(self):
        if not self.experiment:
            return
        self.counts.export_experiment(self.experiment["id"], self.data_root / "validation" / "exports")
        record = ResearchRecordExporter(self.store).export(self.experiment["id"])
        messagebox.showinfo(
            "实验报告已生成",
            f"我的实验报告已生成：\n{record.docx_path}\n\n同时生成了 PDF 和实验数据 Excel。",
            parent=self,
        )
    def close(self):
        self.closing=True
        self.pause_prediction_video()
        self.worker.close()
