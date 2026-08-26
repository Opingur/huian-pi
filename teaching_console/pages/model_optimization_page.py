"""Eight-stage YOLO fine-tune teaching workflow (UI only; no local training)."""
from __future__ import annotations

import csv
import json
from datetime import date
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from teaching_console.runtime_paths import ensure_writable_data_root
from teaching_console.services.model_deployment_service import DeploymentError, ModelDeploymentService
from teaching_console.services.model_optimization_service import (
    ABComparisonService, BoundingBox, CandidateModelManager, CanvasImageTransform,
    ColabPackageBuilder, DatasetBuilder,
)
from teaching_console.services.model_optimization_vision_service import ModelOptimizationVisionService
from teaching_console.services.ai_growth_experiment_service import (
    CHILD_DIFFICULTY_REASONS, challenge_feedback_rows, required_split_message, split_label, summarize_growth,
)
from teaching_console.services.ai_growth_record_exporter import AIGrowthRecordExporter
from teaching_console.services.research_store import ResearchStore
from teaching_console.services.vision_teaching_service import VisionTeachingWorker, load_vision_config
from teaching_console.ui_zoom import CONTROL_MASK, scaled_value


BASE_VIEW_SIZE = (720, 480)


class ModelOptimizationPage(ttk.Frame):
    """Keep evidence and UI state local; all model calls use existing PersonDetector."""

    def __init__(self, master, root_path: Path, open_source) -> None:
        super().__init__(master)
        self.root_path, self.open_source = Path(root_path), open_source
        self.data_root = ensure_writable_data_root(self.root_path)
        self.config = load_vision_config(self.root_path)
        self.store = ResearchStore(self.data_root)
        self.research_choices = {"不关联研究记录": None}
        self.research_var = tk.StringVar()
        self._refresh_research_choices()
        self.worker = VisionTeachingWorker(ModelOptimizationVisionService(self.root_path))
        self.deploy = ModelDeploymentService()
        self.token = 0; self.busy = False; self.closing = False; self.video = None; self.ab_completed = False
        self.project_id = None; self.growth_project_ids: set[str] = set(); self.last_ab_result = None; self.frame_rows = []; self.current_frame = None
        self.raw_frame = None; self.boxes: list[BoundingBox] = []; self.system_boxes: list[BoundingBox] = []
        self.undo: list[list[BoundingBox]] = []; self.selected = None; self.drag = None; self.transform = None
        self.photo = None; self._zoom_factor = 1.0
        self.video_var = tk.StringVar(value="还没有选择图片来源")
        self.current_split_var = tk.StringVar(value="请先选择学习视频")
        self.status_var = tk.StringVar(value="第 1 关：选择一段视频，找出 AI 没看清的画面。")
        self.dataset_var = tk.StringVar(value="学习资料：还没有完成框选")
        self.candidate_var = tk.StringVar(value="成长后的 AI：还没有导入")
        self.progress_var = tk.StringVar(value="今天进度：0 张图片已完成框选")
        self.analysis_progress_var = tk.StringVar(value="AI 筛选进度：请先选择视频。")
        self.analysis_sample_total = 0
        self.annotation_info = tk.StringVar(value="当前图片：—")
        self.student_reason_var = tk.StringVar(value="")
        self.challenge_detail_var = tk.StringVar(value="完成真实比较后，这里会显示一张小测图片的前后结果。")
        self.limit_var = tk.StringVar(value="12"); self.split_var = tk.StringVar(value="train"); self.research_var = tk.StringVar(value="不关联研究记录"); self.teacher_tools_visible = False
        self.show_system_var = tk.BooleanVar(value=True); self.restart_var = tk.StringVar(value=""); self.challenge_rows_by_id = {}
        self._scroll(); self._build(); self.after(40, self._drain)

    def _refresh_research_choices(self) -> None:
        current = getattr(self, "research_var", tk.StringVar(value="不关联研究记录")).get()
        self.research_choices = {"不关联研究记录": None}
        for experiment in self.store.list_experiments():
            label = f"{experiment['name']}（{Path(experiment['video_path']).name}）"
            self.research_choices[label] = experiment['id']
        if current in self.research_choices:
            self.research_var.set(current)
        elif hasattr(self, "research_var"):
            self.research_var.set("不关联研究记录")

    def _selected_research_id(self):
        return self.research_choices.get(self.research_var.get())

    def toggle_teacher_tools(self) -> None:
        if self.teacher_tools_visible:
            self.tabs.forget(self.stage8); self.teacher_tools_visible = False
        else:
            self.tabs.add(self.stage8, text="教师工具（部署与回滚）"); self.teacher_tools_visible = True

    def _scroll(self) -> None:
        self.canvas = tk.Canvas(self, highlightthickness=0); self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set); self.canvas.pack(side="left", fill="both", expand=True); self.bar.pack(side="right", fill="y")
        self.body = ttk.Frame(self.canvas, padding=12); self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.window, width=event.width))
        self.bind("<Enter>", lambda _event: self.canvas.bind_all("<MouseWheel>", self._wheel, add="+"))
        self.bind("<Leave>", lambda _event: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, event):
        if event.state & CONTROL_MASK: return None
        self.canvas.yview_scroll(-int(event.delta / 120 or (1 if event.delta < 0 else -1)), "units"); return "break"

    def _build(self) -> None:
        ttk.Label(self.body, text="今天的任务：帮 AI 认清楼道里的人", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            self.body,
            text="你会完成两关：找出 AI 容易数错的画面 → 用鼠标框出每个人的正确答案。",
            wraplength=1050,
        ).pack(anchor="w", pady=(2, 4))
        ttk.Label(self.body, textvariable=self.progress_var, foreground="#665500").pack(anchor="w")
        ttk.Label(
            self.body,
            text="说明：你的框会成为本次困难帧实验的真实研究资料，用来记录 AI 在什么画面里容易数错。",
            wraplength=1050,
            foreground="#555555",
        ).pack(anchor="w", pady=(2, 8))
        self._build_export_workflow()
        link = ttk.Frame(self.body); link.pack(anchor="w", pady=(0, 6))
        ttk.Label(link, text="关联本次人数研究记录（可选）：").pack(side="left")
        self.research_box = ttk.Combobox(link, textvariable=self.research_var, values=tuple(self.research_choices), width=34, state="readonly")
        self.research_box.pack(side="left", padx=4)
        ttk.Button(link, text="刷新", command=lambda: (self._refresh_research_choices(), self.research_box.configure(values=tuple(self.research_choices)))).pack(side="left")
        self.tabs = ttk.Notebook(self.body); self.tabs.pack(fill="both", expand=True)
        self.stage1 = self._tab("第 1 关：找出 AI 没看清的画面")
        self.stage2 = self._tab("第 2 关：告诉 AI 正确答案")
        self.stage3 = ttk.Frame(self.tabs, padding=10)  # 保留内部研究能力，但不向孩子显示训练验证页。
        self.stage8 = ttk.Frame(self.tabs, padding=10)
        self._hard_frames(); self._annotation(); self._growth_verification(); self._deploy()
        ttk.Button(self.body, text="显示 / 隐藏教师工具", command=self.toggle_teacher_tools).pack(anchor="e", pady=(4, 0))
        ttk.Label(self.body, textvariable=self.status_var, wraplength=1050, foreground="#444444").pack(anchor="w", pady=(8, 0))
    def _tab(self, title):
        page = ttk.Frame(self.tabs, padding=10); self.tabs.add(page, text=title); return page

    def _build_export_workflow(self) -> None:
        """Show children what their observation becomes after one experiment."""
        workflow = ttk.LabelFrame(
            self.body,
            text="完成后，你会得到什么？",
            padding=8,
        )
        workflow.pack(fill="x", pady=(0, 8))
        steps = (
            ("1. AI 帮你找画面", "从视频里挑出值得认真观察的困难画面。"),
            ("2. 你写下观察", "选择画面为什么难，例如人多重叠或有人被遮挡。"),
            ("3. 你框出正确答案", "用鼠标框出每一个人，留下你的真实研究数据。"),
            ("4. 一键整理研究资料", "导出 Word 实验报告和 Excel 数据表，保存你的发现和心得。"),
        )
        for column, (title, description) in enumerate(steps):
            item = ttk.Frame(workflow)
            item.grid(row=0, column=column, sticky="nw", padx=(0, 14 if column < len(steps) - 1 else 0))
            ttk.Label(item, text=title, font=("Segoe UI", 10, "bold")).pack(anchor="w")
            ttk.Label(item, text=description, wraplength=210, justify="left", foreground="#555555").pack(anchor="w", pady=(2, 0))
            workflow.columnconfigure(column, weight=1)
        ttk.Label(
            workflow,
            text="导出内容：Word 用来讲清楚这次研究；Excel 保留逐张画面的 AI 人数、你的框选人数和观察原因。不生成 PDF。",
            wraplength=1050,
            foreground="#176b87",
        ).grid(row=1, column=0, columnspan=len(steps), sticky="w", pady=(8, 0))

    def _baseline(self):
        ttk.Label(self.stage1, text="先看看原来的 AI 在同一组人工正确答案上表现怎样。之后会用同一组图片比较成长后的 AI 是否真的更准确。", wraplength=1000).pack(anchor="w")

    def _hard_frames(self):
        ttk.Label(self.stage1, text="先找出 AI 容易数错的画面", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(
            self.stage1,
            text="选择一段人多、遮挡、距离远或光线复杂的视频，让 AI 帮你找出值得仔细观察的画面。",
            wraplength=1000,
        ).pack(anchor="w", pady=(2, 6))
        sources = ttk.Frame(self.stage1); sources.pack(anchor="w", pady=(0, 4))
        ttk.Button(sources, text="选择困难帧实验视频", command=lambda: self.choose_video("train")).pack(side="left")


        ttk.Label(self.stage1, textvariable=self.current_split_var, foreground="#665500").pack(anchor="w")
        ttk.Label(self.stage1, textvariable=self.video_var, wraplength=1000).pack(anchor="w", pady=(2, 6))
        actions = ttk.Frame(self.stage1); actions.pack(anchor="w", pady=(0, 6))
        ttk.Button(actions, text="找出值得观察的图片", command=self.analyze).pack(side="left")
        ttk.Button(actions, text="导出研究记录（Word + Excel）", command=self.save_growth_record).pack(side="left", padx=8)
        ttk.Label(actions, text="处理完一段视频后可先保存研究记录；每段视频最多挑出 12 张，避免逐帧做作业。", foreground="#555555").pack(side="left", padx=2)
        ttk.Label(self.stage1, textvariable=self.analysis_progress_var, foreground="#176b87").pack(anchor="w", pady=(0, 4))
        columns = ("frame", "time", "count", "status", "reason")
        self.frame_tree = ttk.Treeview(self.stage1, columns=columns, show="headings", height=9)
        for key, label, width in (("frame", "图片编号", 80), ("time", "视频时间", 90), ("count", "AI 原来数", 90), ("status", "完成情况", 100), ("reason", "为什么值得仔细看", 500)):
            self.frame_tree.heading(key, text=label); self.frame_tree.column(key, width=width, anchor="w")
        self.frame_tree.pack(fill="both", expand=True); self.frame_tree.bind("<<TreeviewSelect>>", self.select_frame)
        reason_box = ttk.LabelFrame(self.stage1, text="你觉得这张图片为什么难？", padding=6); reason_box.pack(fill="x", pady=8)
        for reason in CHILD_DIFFICULTY_REASONS:
            ttk.Radiobutton(reason_box, text=reason, value=reason, variable=self.student_reason_var).pack(side="left", padx=(0, 14))
        ttk.Button(reason_box, text="保存我的观察", command=self.save_student_reason).pack(side="left", padx=4)
        row = ttk.Frame(self.stage1); row.pack(fill="x")
        self.preview = tk.Canvas(row, width=480, height=320, background="#202020", highlightthickness=1, highlightbackground="#999999")
        self.preview.pack(side="left")
        tips = ttk.Frame(row); tips.pack(side="left", fill="y", padx=12)
        ttk.Label(tips, text="本关小提示", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(tips, text="先点图片，再看原始画面。\n\n不要急着相信 AI 的人数；你要找出它为什么可能看不清。\n\n保留的图片会进入下一关，用鼠标框出每一个人。", wraplength=300, justify="left").pack(anchor="w", pady=6)
        buttons = ttk.Frame(tips); buttons.pack(anchor="w", pady=8)
        ttk.Button(buttons, text="保留这张", command=lambda: self.set_kept(True)).pack(side="left")
        ttk.Button(buttons, text="跳过", command=lambda: self.set_kept(False)).pack(side="left", padx=5)
    def _annotation(self):
        ttk.Label(self.stage2, text="用鼠标框出每一个人", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(
            self.stage2,
            text="左键拖动新建一个人的框；点击已有框可以移动或拉边调整。这里的框就是你给 AI 的正确答案。",
            wraplength=1000,
        ).pack(anchor="w", pady=(2, 6))
        controls = ttk.Frame(self.stage2); controls.pack(fill="x", pady=6)
        ttk.Button(controls, text="上一张", command=lambda: self.move_frame(-1)).pack(side="left")
        ttk.Button(controls, text="保存这一张", command=self.save_boxes).pack(side="left", padx=4)
        ttk.Button(controls, text="保存并下一张", command=lambda: (self.save_boxes(), self.move_frame(1))).pack(side="left")
        ttk.Checkbutton(controls, text="显示 AI 原来识别的框", variable=self.show_system_var, command=self.toggle_system).pack(side="left", padx=12)
        ttk.Button(controls, text="撤销", command=self.undo_box).pack(side="left")
        ttk.Label(controls, text="Delete 删除选中框；Ctrl+Z 撤销", foreground="#555555").pack(side="left", padx=8)
        ttk.Label(self.stage2, textvariable=self.annotation_info, foreground="#665500").pack(anchor="w")
        self.draw = tk.Canvas(self.stage2, width=BASE_VIEW_SIZE[0], height=BASE_VIEW_SIZE[1], background="#202020", highlightthickness=1, highlightbackground="#999999")
        self.draw.pack(anchor="w", pady=6); self.draw.bind("<ButtonPress-1>", self.press); self.draw.bind("<B1-Motion>", self.motion); self.draw.bind("<ButtonRelease-1>", self.release); self.draw.bind("<Delete>", lambda _e: self.delete_box()); self.draw.bind("<Control-z>", lambda _e: self.undo_box())
        ttk.Label(self.stage2, text="完成后会记录：AI 原来数了多少人、你框出了多少人、你认为它为什么容易出错。", wraplength=1000, foreground="#555555").pack(anchor="w")
    def _dataset(self):
        ttk.Label(self.stage4, text="把已经保存的正确答案整理成 AI 可以学习的成长资料。系统会保持视频之间独立，避免把练习答案混到验证答案里。", wraplength=1000).pack(anchor="w")
        ttk.Button(self.stage4, text="整理 AI 成长资料", command=self.build_dataset).pack(anchor="w", pady=8)

    def _colab(self):
        ttk.Label(self.stage5, text="成长资料准备好后，请老师协助在训练环境中让 AI 学习。这个步骤不会影响正在运行的楼道系统。", wraplength=1000).pack(anchor="w")
        row = ttk.Frame(self.stage5); row.pack(anchor="w", pady=8)
        ttk.Button(row, text="准备给老师的训练资料", command=self.build_package).pack(side="left")
        ttk.Label(self.stage5, text="老师会根据资料完成训练，并把成长后的模型文件带回这里比较。", wraplength=1000).pack(anchor="w")

    def _import(self):
        ttk.Label(self.stage6, text="由老师选择成长后的 AI 模型文件。它会安全保存为候选模型，不会替换原来的基础 AI。", wraplength=1000).pack(anchor="w")
        ttk.Button(self.stage6, text="导入成长后的 AI", command=self.import_candidate).pack(anchor="w", pady=8)

    def _ab(self):
        ttk.Label(self.stage7, text="让原来的 AI 和成长后的 AI 看完全相同的人工正确答案。重点看：谁和人工数的人数更接近。", wraplength=1000).pack(anchor="w")
        ttk.Button(self.stage7, text="比较优化前 VS 优化后", command=self.run_ab).pack(anchor="w", pady=8)
        self.ab_var = tk.StringVar(value="尚未运行 A/B。")
        ttk.Label(self.stage7, textvariable=self.ab_var, wraplength=1000).pack(anchor="w")
        row = ttk.Frame(self.stage7); row.pack(anchor="w", pady=8); ttk.Button(row, text="接受候选模型", command=lambda: self.candidate_state("accepted")).pack(side="left"); ttk.Button(row, text="放弃候选模型", command=lambda: self.candidate_state("rejected")).pack(side="left", padx=6)

    def _growth_verification(self):
        ttk.Label(self.stage3, text="让 AI 在新图片上考试", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(
            self.stage3,
            text="小测图片来自独立视频，不交给 AI 学习。这样比较成长前和成长后的模型，才能知道它是不是真的学会了。",
            wraplength=1000,
        ).pack(anchor="w", pady=(2, 6))
        self.readiness_var = tk.StringVar(value="准备好学习图片、检查图片和小测图片后，才能开始真实训练与验证。")
        ttk.Label(self.stage3, textvariable=self.readiness_var, wraplength=1000, foreground="#665500").pack(anchor="w")
        self.instant_feedback_var = tk.StringVar(value="现场即时成果：请先在第 2 关完成一张人工框选。")
        ttk.Label(self.stage3, textvariable=self.instant_feedback_var, wraplength=1000, foreground="#176b87").pack(anchor="w", pady=(6, 2))
        ttk.Label(self.stage3, text="这里会自动记录你刚刚找出的 AI 漏数或多数。真实模型的成长验证由老师在隐藏的教师工具中准备，不需要孩子操作。", wraplength=1000, foreground="#555555").pack(anchor="w")
        child_controls = ttk.Frame(self.stage3); child_controls.pack(anchor="w", pady=8)
        ttk.Button(child_controls, text="导出研究记录（Word + Excel）", command=self.save_growth_record).pack(side="left")
        teacher_actions = ttk.LabelFrame(self.stage8, text="AI 成长实验：教师训练与真实验证", padding=8); teacher_actions.pack(fill="x", pady=(0, 8))
        ttk.Label(teacher_actions, text="这些操作只在老师已准备训练环境或真实候选模型时使用；孩子不需要操作。", wraplength=1000).pack(anchor="w")
        teacher_buttons = ttk.Frame(teacher_actions); teacher_buttons.pack(anchor="w", pady=(6, 0))
        ttk.Button(teacher_buttons, text="整理学习资料", command=self.build_dataset).pack(side="left")
        ttk.Button(teacher_buttons, text="准备老师训练资料", command=self.build_package).pack(side="left", padx=5)
        ttk.Button(teacher_buttons, text="导入成长后的 AI", command=self.import_candidate).pack(side="left")
        ttk.Button(teacher_buttons, text="在小测图片上验证", command=self.run_ab).pack(side="left", padx=5)
        self.ab_var = tk.StringVar(value="还没有进行真实比较。")
        ttk.Label(self.stage3, textvariable=self.ab_var, wraplength=1000).pack(anchor="w", pady=(2, 8))
        columns = ("time", "actual", "before", "after", "result")
        self.challenge_tree = ttk.Treeview(self.stage3, columns=columns, show="headings", height=6)
        for key, label, width in (("time", "小测图片", 150), ("actual", "人工正确人数", 110), ("before", "成长前 AI", 100), ("after", "成长后 AI", 100), ("result", "这一张的结果", 180)):
            self.challenge_tree.heading(key, text=label); self.challenge_tree.column(key, width=width, anchor="center")
        self.challenge_tree.pack(fill="x", expand=True); self.challenge_tree.bind("<<TreeviewSelect>>", self.select_challenge_result)
        result_row = ttk.Frame(self.stage3); result_row.pack(fill="x", pady=8)
        self.challenge_preview = tk.Canvas(result_row, width=480, height=320, background="#202020", highlightthickness=1, highlightbackground="#999999")
        self.challenge_preview.pack(side="left")
        ttk.Label(result_row, textvariable=self.challenge_detail_var, wraplength=360, justify="left").pack(side="left", anchor="n", padx=12)
    def _deploy(self):
        ttk.Label(self.stage8, text="目标设备：huian-pi    远端项目：/home/x/Huian_YOLO。部署只上传独立候选文件并备份远端 config.json；失败自动回滚，不删除也不覆盖 yolov8n.pt。", wraplength=1000).pack(anchor="w")
        self.rollback_var = tk.StringVar(value="")
        row = ttk.Frame(self.stage8); row.pack(anchor="w", pady=8); ttk.Button(row, text="测试 SSH", command=self.ssh_check).pack(side="left"); ttk.Button(row, text="运行自检", command=self.ssh_self_check).pack(side="left", padx=5); ttk.Button(row, text="部署模型", command=self.ssh_deploy).pack(side="left"); ttk.Button(row, text="回滚上一模型", command=self.ssh_rollback).pack(side="left", padx=5)
        ttk.Label(self.stage8, text="已核实的重启命令（必填，不会猜测）：").pack(anchor="w"); ttk.Entry(self.stage8, textvariable=self.restart_var, width=70).pack(anchor="w")
        ttk.Label(self.stage8, text="远端回滚记录（部署成功后自动填入）：").pack(anchor="w", pady=(6, 0)); ttk.Entry(self.stage8, textvariable=self.rollback_var, width=85).pack(anchor="w")

    def choose_video(self, split_name: str = "train"):
        path = filedialog.askopenfilename(parent=self, filetypes=(("视频", "*.mp4 *.avi *.mov *.mkv"),))
        if not path:
            return
        self.split_var.set(split_name)
        self.current_split_var.set("当前处理：困难帧实验视频" if split_name == "train" else f"当前处理：{split_label(split_name)}")
        self._send("open_video", Path(path))
        self.status_var.set("正在打开视频…")
    def analyze(self):
        try:
            limit = int(self.limit_var.get())
            assert 5 <= limit <= 25
        except Exception:
            messagebox.showwarning("输入错误", "候选数量必须是 5 到 25。", parent=self)
            return
        if self.video is None:
            messagebox.showwarning("请先选择视频", "请先选择学习、检查或小测视频。", parent=self)
            return
        self.analysis_sample_total = 0
        self.analysis_progress_var.set("AI 正在准备抽样画面…")
        self._send("analyze_difficult_frames", limit)
        self.status_var.set("AI 正在找出容易看不清的图片，请耐心等待进度完成。")
    def _send(self, operation, *args): self.token += 1; self.busy = True; self.worker.submit(self.token, operation, *args)
    def _drain(self):
        if self.closing: return
        try:
            while True:
                result = self.worker.results.get_nowait()
                if result.token != self.token: continue
                if result.operation == "analyze_difficult_frames_progress":
                    completed, total = result.value
                    self.analysis_sample_total = int(total)
                    self.analysis_progress_var.set(f"AI 正在观察第 {completed} / {total} 个抽样画面…")
                    self.status_var.set(f"AI 正在筛选困难画面：第 {completed} / {total} 个抽样画面。")
                    continue
                self.busy = False
                if result.error:
                    self.status_var.set("错误：" + result.error)
                    if result.operation == "analyze_difficult_frames":
                        self.analysis_progress_var.set("AI 筛选没有完成：" + result.error)
                    continue
                try:
                    self._handle(result.operation, result.value)
                except Exception as error:
                    self.busy = False
                    self.status_var.set("处理结果失败：" + str(error))
                    if result.operation == "analyze_difficult_frames":
                        self.analysis_progress_var.set("AI 已完成观察，但候选列表保存失败：" + str(error))
        except queue.Empty: pass
        self.after(40, self._drain)

    def _handle(self, operation, value):
        if operation == "open_video":
            self.video = value
            self.current_frame = None; self.raw_frame = None; self.boxes = []; self.system_boxes = []
            self.video_var.set(f"当前视频：{Path(value.path).name} | {value.width}×{value.height} | {value.fps:.2f} FPS")
            self.analysis_progress_var.set("已打开视频，正在读取第 1 帧原始画面…")
            self._send("read_raw", 0)
            self.status_var.set("视频已打开，正在显示第 1 帧原始画面。")
        elif operation == "analyze_difficult_frames":
            self._save_recommendations(value)
        elif operation == "read_raw":
            self._show_raw(value)
        elif operation == "detect":
            self.system_boxes = [BoundingBox(*row.bbox) for row in value.rows]
            self._redraw()
    def _save_recommendations(self, recommendations):
        source = str(self.video.path)
        split_name = self.split_var.get()
        projects = self.store.list_detection_annotation_projects("huian_person_v1")
        # The child-facing difficult-frame lab has one video workflow.  Older
        # records can still carry train/val/test labels, so reuse by source
        # video instead of rejecting an otherwise valid historical project.
        existing = next((project for project in projects if project["source_video"] == source), None)
        if existing is None:
            self.project_id = self.store.create_detection_annotation_project(
                f"{Path(source).stem}_{split_name}", source, split_name, "huian_person_v1"
            )
        else:
            self.project_id = existing["id"]
        self.growth_project_ids.add(self.project_id)
        current = self.store.detection_frame_annotations(self.project_id)
        known_frames = {row["frame_index"] for row in current}
        for item in recommendations:
            if item.frame_index not in known_frames:
                self.store.create_detection_frame_annotation(
                    self.project_id, item.frame_index, item.time_seconds, self.video.width, self.video.height,
                    system_count=item.system_count, average_confidence=item.average_confidence,
                    minimum_confidence=item.minimum_confidence, recommendation_reasons="；".join(item.reasons),
                )
        self.frame_rows = self.store.detection_frame_annotations(self.project_id)
        self._refresh_frames()
        self._update_progress()
        total_text = str(self.analysis_sample_total) if self.analysis_sample_total else "若干"
        self.analysis_progress_var.set(f"AI 筛选完成：从 {total_text} 个抽样画面中选出 {len(self.frame_rows)} 张。")
        self.status_var.set(f"已载入 {len(self.frame_rows)} 张困难帧候选；已自动显示第一张，请写下你的观察。")
        if self.frame_rows:
            first = self.frame_rows[0]
            self.frame_tree.selection_set(first["id"]); self.frame_tree.focus(first["id"]); self.select_frame()
    def _refresh_frames(self):
        existing_rows = self.frame_tree.get_children()
        if existing_rows:
            self.frame_tree.delete(*existing_rows)
        for row in self.frame_rows:
            status = "已完成框选" if row["annotation_completed"] else ("待框选" if row["kept"] else "已跳过")
            reason = row["student_reason"] or row["recommendation_reasons"] or "待观察"
            self.frame_tree.insert(
                "", "end", iid=row["id"],
                values=(row["frame_index"], f"{row['video_time_seconds']:.2f}s", row["system_count"], status, reason),
            )

    def _update_progress(self):
        completed = total = 0
        for project in self.store.list_detection_annotation_projects("huian_person_v1"):
            rows = self.store.detection_frame_annotations(project["id"], include_skipped=False)
            total += len(rows)
            completed += sum(bool(row["annotation_completed"]) for row in rows)
        self.progress_var.set(f"今天进度：{completed} / {total} 张保留图片已完成框选")

    def save_student_reason(self):
        if self.current_frame is None:
            messagebox.showwarning("请先选图片", "先从列表中选一张图片，再说说它为什么难。", parent=self)
            return
        reason = self.student_reason_var.get().strip()
        if not reason:
            messagebox.showwarning("请选择原因", "请选择一种你观察到的困难原因。", parent=self)
            return
        self.store.update_detection_frame_annotation(self.current_frame["id"], student_reason=reason)
        self.current_frame = self.store.get_detection_frame_annotation(self.current_frame["id"])
        self.frame_rows = self.store.detection_frame_annotations(self.project_id)
        self._refresh_frames()
        self.status_var.set(f"已记录你的观察：{reason}。下一关请用鼠标框出每一个人。")
    def select_frame(self, _event=None):
        selected = self.frame_tree.selection()
        if not selected or self.busy:
            return
        self.current_frame = self.store.get_detection_frame_annotation(selected[0])
        self.boxes = [BoundingBox(row["x1"], row["y1"], row["x2"], row["y2"]) for row in self.store.detection_person_boxes(selected[0])]
        self.student_reason_var.set(self.current_frame["student_reason"])
        self.undo = []
        self.system_boxes = []
        self._send("read_raw", self.current_frame["frame_index"])
    def set_kept(self, kept):
        if self.current_frame is None:
            return
        self.store.update_detection_frame_annotation(self.current_frame["id"], kept=kept)
        self.current_frame = self.store.get_detection_frame_annotation(self.current_frame["id"])
        self.frame_rows = self.store.detection_frame_annotations(self.project_id)
        self._refresh_frames()
        self._update_progress()
    def _show_raw(self, packet):
        self.raw_frame = packet.frame_bgr; self._save_raw_frame(); self._redraw(); self._redraw_preview()
        if self.current_frame is None:
            self.analysis_progress_var.set("已显示视频第 1 帧原始画面；现在可以让 AI 开始筛选。")
        elif self.show_system_var.get():
            self._send("detect", self.current_frame["frame_index"])

    def _redraw_preview(self):
        if not hasattr(self, "preview") or self.raw_frame is None:
            return
        from PIL import Image, ImageTk
        height, width = self.raw_frame.shape[:2]
        scale = min(480 / width, 320 / height)
        shown = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = Image.fromarray(self.raw_frame[:, :, ::-1])
        image.thumbnail(shown)
        self.preview_photo = ImageTk.PhotoImage(image)
        self.preview.delete("all")
        self.preview.create_image((480 - shown[0]) / 2, (320 - shown[1]) / 2, anchor="nw", image=self.preview_photo)
    def _save_raw_frame(self):
        if self.current_frame is None or self.raw_frame is None: return
        path = self.data_root / "annotation_frames" / self.project_id / f"frame_{self.current_frame['frame_index']:06d}.jpg"; path.parent.mkdir(parents=True, exist_ok=True)
        import cv2
        cv2.imwrite(str(path), self.raw_frame); self.store.update_detection_frame_annotation(self.current_frame["id"], image_path=path)
        self.current_frame = self.store.get_detection_frame_annotation(self.current_frame["id"])

    def _redraw(self):
        self.draw.delete("all")
        if self.raw_frame is None: return
        from PIL import Image, ImageTk
        height, width = self.raw_frame.shape[:2]; max_w, max_h = (scaled_value(value, self._zoom_factor) for value in BASE_VIEW_SIZE)
        scale = min(max_w / width, max_h / height); shown = (round(width * scale), round(height * scale)); offset = ((max_w - shown[0]) / 2, (max_h - shown[1]) / 2)
        image = Image.fromarray(self.raw_frame[:, :, ::-1]); image.thumbnail(shown); self.photo = ImageTk.PhotoImage(image); self.draw.configure(width=max_w, height=max_h); self.draw.create_image(offset[0], offset[1], anchor="nw", image=self.photo)
        self.transform = CanvasImageTransform(width, height, offset[0], offset[1], shown[0], shown[1])
        for index, box in enumerate(self.system_boxes if self.show_system_var.get() else []): self._draw_box(box, "#f2a900", f"YOLO {index + 1}")
        for index, box in enumerate(self.boxes): self._draw_box(box, "#27d17f" if index != self.selected else "#00e5ff", f"person {index + 1}")
        if self.current_frame is not None: self.annotation_info.set(f"当前帧：{self.frame_rows.index(next(row for row in self.frame_rows if row['id']==self.current_frame['id'])) + 1} / {len(self.frame_rows)} | 人工框数：{len(self.boxes)} | 系统检测数：{self.current_frame['system_count']}")

    def _draw_box(self, box, color, label):
        x1, y1 = self.transform.image_to_canvas(box.x1, box.y1); x2, y2 = self.transform.image_to_canvas(box.x2, box.y2); self.draw.create_rectangle(x1, y1, x2, y2, outline=color, width=2); self.draw.create_text(x1 + 3, max(8, y1 - 8), text=label, anchor="sw", fill=color)

    def _hit(self, x, y):
        image_x, image_y = self.transform.canvas_to_image(x, y); margin = 8 / (self.transform.display_width / self.transform.original_width)
        for index in reversed(range(len(self.boxes))):
            box = self.boxes[index]
            if box.x1 <= image_x <= box.x2 and box.y1 <= image_y <= box.y2:
                edge = ("left" if abs(image_x-box.x1)<margin else "right" if abs(image_x-box.x2)<margin else "") + ("_top" if abs(image_y-box.y1)<margin else "_bottom" if abs(image_y-box.y2)<margin else "")
                return index, edge.strip("_") or "move", image_x, image_y
        return None, "new", image_x, image_y

    def press(self, event):
        if self.transform is None: return
        index, action, x, y = self._hit(event.x, event.y); self.selected = index; self._before_drag = list(self.boxes); self.drag = (action, x, y, self.boxes[index] if index is not None else None); self._redraw()

    def motion(self, event):
        if not self.drag or self.transform is None: return
        action, start_x, start_y, original = self.drag; x, y = self.transform.canvas_to_image(event.x, event.y)
        if action == "new": self._preview = BoundingBox(start_x, start_y, x, y).normalized(); self._redraw(); self._draw_box(self._preview, "#00e5ff", "new")
        elif action == "move": self.boxes[self.selected] = original.moved(x-start_x, y-start_y, self.transform.original_width, self.transform.original_height); self._redraw()
        else: self.boxes[self.selected] = original.resized(action, x, y, self.transform.original_width, self.transform.original_height); self._redraw()

    def release(self, event):
        if not self.drag or self.transform is None: return
        action, start_x, start_y, _original = self.drag; x, y = self.transform.canvas_to_image(event.x, event.y)
        if action == "new":
            box = BoundingBox(start_x, start_y, x, y).normalized()
            if box.x2-box.x1 >= 2 and box.y2-box.y1 >= 2: self.undo.append(list(self.boxes)); self.boxes.append(box); self.selected = len(self.boxes)-1
        else: self.undo.append(self._before_drag)
        self.drag = None; self._redraw()

    def delete_box(self):
        if self.selected is not None: self.undo.append(list(self.boxes)); self.boxes.pop(self.selected); self.selected = None; self._redraw()
    def undo_box(self):
        if self.undo: self.boxes = self.undo.pop(); self.selected = None; self._redraw()
    def save_boxes(self):
        if self.current_frame is None:
            messagebox.showwarning("请先选图片", "请先从第 1 关选择一张保留的图片。", parent=self)
            return
        self.store.replace_detection_person_boxes(
            self.current_frame["id"],
            [dict(x1=box.x1, y1=box.y1, x2=box.x2, y2=box.y2, class_id=0) for box in self.boxes],
        )
        self.store.update_detection_frame_annotation(self.current_frame["id"], annotation_completed=True)
        self.current_frame = self.store.get_detection_frame_annotation(self.current_frame["id"])
        self.frame_rows = self.store.detection_frame_annotations(self.project_id)
        self._refresh_frames()
        self._update_progress()
        self._update_instant_feedback()
        self._redraw()
        self.status_var.set("正确答案已保存：AI 原来数 {} 人；你框出 {} 人。".format(self.current_frame["system_count"], len(self.boxes)))
    def _update_instant_feedback(self):
        if self.current_frame is None:
            return
        original_count = int(self.current_frame["system_count"] or 0)
        child_count = len(self.boxes)
        difference = child_count - original_count
        if difference > 0:
            result = f"AI 少数了 {difference} 人"
        elif difference < 0:
            result = f"AI 多数了 {-difference} 人"
        else:
            result = "这张人数与孩子的答案相同"
        self.instant_feedback_var.set(
            f"现场即时成果：AI 原来数 {original_count} 人，你框出 {child_count} 人，{result}。"
            "这说明你找到了需要学习的正确答案；还不表示模型已经训练完成。"
        )

    def move_frame(self, direction):
        if self.current_frame is None: return
        kept = [row for row in self.frame_rows if row["kept"]]; index = next((i for i,row in enumerate(kept) if row["id"] == self.current_frame["id"]), 0); target = kept[max(0, min(len(kept)-1, index+direction))] if kept else None
        if target: self.frame_tree.selection_set(target["id"]); self.select_frame()
    def toggle_system(self):
        if self.show_system_var.get() and self.current_frame is not None: self._send("detect", self.current_frame["frame_index"])
        else: self._redraw()

    def _dataset_rows(self):
        projects = self.store.list_detection_annotation_projects("huian_person_v1")
        assignments = self.store.validate_detection_dataset_splits("huian_person_v1")
        rows = []
        for project in projects:
            for frame in self.store.detection_frame_annotations(project["id"], include_skipped=False):
                if not frame["image_path"] or not frame["annotation_completed"]:
                    continue
                rows.append({
                    "source_video": frame["source_video"], "frame_path": frame["image_path"],
                    "frame_index": frame["frame_index"], "image_width": frame["image_width"],
                    "image_height": frame["image_height"],
                    "boxes": [BoundingBox(box["x1"], box["y1"], box["x2"], box["y2"])
                              for box in self.store.detection_person_boxes(frame["id"])],
                })
        return rows, assignments

    @staticmethod
    def _missing_completed_splits(rows, assignments):
        completed = {assignments[row["source_video"]] for row in rows}
        return [split for split in ("train", "val", "test") if split not in completed]
    def build_dataset(self):
        try:
            rows, assignments = self._dataset_rows()
            message = required_split_message(assignments)
            if message:
                raise ValueError(message)
            missing = self._missing_completed_splits(rows, assignments)
            if missing:
                names = "、".join(split_label(split).split("（", 1)[0] for split in missing)
                raise ValueError(f"{names}还没有完成框选；请先在第 2 关画出每一个人。")
            result = DatasetBuilder(self.data_root).build("huian_person_v1", rows, assignments)
            self.dataset_var.set(f"学习资料：已完成 {result.frame_count} 张图片、{result.annotation_count} 个人体框")
            self.readiness_var.set("学习资料已整理。下一步由老师使用真实 YOLO 训练资料训练，并把 best.pt 带回这里。")
            self.status_var.set(f"AI 学习资料已生成：{result.dataset_dir}")
        except Exception as error:
            messagebox.showerror("还不能整理学习资料", str(error), parent=self)
    def build_package(self):
        try:
            package = ColabPackageBuilder(self.data_root, template_root=self.root_path).build(
                self.data_root / "datasets" / "huian_person_v1", "huian_person_v1"
            )
            research_id = self._selected_research_id()
            self.model_experiment_id = self.store.create_model_experiment(
                "huian_person_v1", "huian_person_v1", self.config.model_path,
                research_experiment_id=research_id, epochs=50, imgsz=640,
                training_package_path=package.package_dir,
            )
            if research_id:
                self.store.log_activity(research_id, "prepare_ai_growth", "完成困难图片框选，准备让 AI 学习")
            self.readiness_var.set("训练资料已准备。老师完成真实训练后，请导入下载得到的 best.pt。")
            self.status_var.set(f"老师训练资料已准备：{package.package_dir}")
        except Exception as error:
            messagebox.showerror("生成训练资料失败", str(error), parent=self)
    def import_candidate(self):
        source = filedialog.askopenfilename(parent=self, title="选择真实训练后下载的 best.pt", filetypes=(("PyTorch 模型", "*.pt"),))
        if not source:
            return
        try:
            candidate = CandidateModelManager(self.data_root, baseline_model_path=self.config.model_path).import_best_pt(
                "huian_person_v1", Path(source)
            )
            self.candidate_path = candidate.model_path
            self.candidate_var.set(f"成长后的 AI：已导入 {candidate.model_path.name}")
            if not hasattr(self, "model_experiment_id"):
                self.model_experiment_id = self.store.create_model_experiment(
                    "huian_person_v1", "huian_person_v1", self.config.model_path,
                    research_experiment_id=self._selected_research_id(),
                )
            self.store.set_model_candidate(self.model_experiment_id, candidate.model_path, result_metadata_path=candidate.metadata_path)
            record = self.store.get_model_experiment(self.model_experiment_id)
            if record and record["research_experiment_id"]:
                self.store.log_activity(record["research_experiment_id"], "import_ai_growth_model", "导入真实训练后的 AI，准备小测图片验证")
            self.readiness_var.set("成长后的 AI 已导入。现在可以在从未参与学习的小测图片上验证。")
            self.status_var.set("成长后的 AI 已导入；请点击“在小测图片上验证”。")
        except Exception as error:
            messagebox.showerror("导入失败", str(error), parent=self)
    def run_ab(self):
        if not hasattr(self, "candidate_path"):
            messagebox.showwarning("还没有成长后的 AI", "请先由老师完成真实训练并导入 best.pt。", parent=self)
            return
        try:
            from rpi_app.vision.detector import PersonDetector
            import cv2
            rows, assignments = self._dataset_rows()
            test = [row for row in rows if assignments[row["source_video"]] == "test"]
            if not test:
                raise ValueError("没有完成框选的小测图片。小测图片必须来自独立视频，且不能交给 AI 学习。")
            baseline = PersonDetector(self.config.model_path, self.config.confidence)
            candidate = PersonDetector(self.candidate_path, self.config.confidence)
            ground_truth, baseline_predictions, candidate_predictions = [], {}, {}
            for row in test:
                image = cv2.imread(str(row["frame_path"]))
                if image is None:
                    raise FileNotFoundError(f"找不到小测图片：{row['frame_path']}")
                key = f"{row['source_video']}:{row['frame_index']}"
                ground_truth.append({"frame_id": key, "boxes": row["boxes"]})
                baseline_predictions[key] = [BoundingBox(item["x1"], item["y1"], item["x2"], item["y2"]) for item in baseline.detect(image)]
                candidate_predictions[key] = [BoundingBox(item["x1"], item["y1"], item["x2"], item["y2"]) for item in candidate.detect(image)]
            result = ABComparisonService().compare(ground_truth, baseline_predictions, candidate_predictions)
            self.last_ab_result = result
            out = self.data_root / "validation" / "exports" / "model_optimization"; out.mkdir(parents=True, exist_ok=True)
            stem = "baseline_vs_huian_person_v1"
            (out / (stem + ".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            by_key = {f"{row['source_video']}:{row['frame_index']}": row for row in test}
            fields = ("sample", "video", "frame_index", "ground_truth_count", "baseline_count", "candidate_count", "baseline_error", "candidate_error", "baseline_tp", "baseline_fp", "baseline_fn", "candidate_tp", "candidate_fp", "candidate_fn")
            with (out / (stem + ".csv")).open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
                for index, sample in enumerate(result["samples"], start=1):
                    source = by_key[sample["frame_id"]]
                    before, after = sample["baseline"], sample["candidate"]
                    writer.writerow({"sample": index, "video": source["source_video"], "frame_index": source["frame_index"], "ground_truth_count": sample["ground_truth_count"], "baseline_count": before["model_count"], "candidate_count": after["model_count"], "baseline_error": before["absolute_count_error"], "candidate_error": after["absolute_count_error"], "baseline_tp": before["true_positives"], "baseline_fp": before["false_positives"], "baseline_fn": before["false_negatives"], "candidate_tp": after["true_positives"], "candidate_fp": after["false_positives"], "candidate_fn": after["false_negatives"]})
            summary = summarize_growth(result)
            self.ab_var.set(f"成长前平均每张小测图片相差 {summary.baseline_mae:.2f} 人；成长后相差 {summary.candidate_mae:.2f} 人。\n{summary.message}")
            self.challenge_rows_by_id = {row.frame_id: (row, by_key[row.frame_id]) for row in challenge_feedback_rows(result["samples"])}
            self.challenge_tree.delete(*self.challenge_tree.get_children())
            for feedback in self.challenge_rows_by_id.values():
                row, source = feedback
                self.challenge_tree.insert("", "end", iid=row.frame_id, values=(f"{Path(source['source_video']).name} / {source['frame_index']}", row.ground_truth_count, row.baseline_count, row.candidate_count, row.message))
            self.ab_completed = True
            record = self.store.get_model_experiment(self.model_experiment_id) if hasattr(self, "model_experiment_id") else None
            if record and record["research_experiment_id"]:
                self.store.log_activity(record["research_experiment_id"], "compare_ai_growth", "在独立小测图片上完成成长前后真实比较")
            self.status_var.set(f"真实小测图片比较已完成，结果已导出：{out}")
        except Exception as error:
            messagebox.showerror("小测图片验证失败", str(error), parent=self)

    def save_growth_record(self):
        project_ids = list(self.growth_project_ids)
        if not project_ids and self.project_id:
            project_ids = [self.project_id]
        if not project_ids:
            messagebox.showwarning("还没有实验资料", "请先选择一段视频并保留至少一张值得观察的图片。", parent=self)
            return
        try:
            experiment_id = self._selected_research_id()
            if experiment_id is None:
                first = self.store.get_detection_annotation_project(project_ids[0])
                if first is None:
                    raise KeyError(project_ids[0])
                experiment_id = self.store.create_experiment(
                    name=f"AI困难帧实验_{Path(first['source_video']).stem}",
                    video_path=first["source_video"],
                    experiment_type="teaching",
                    description="孩子通过困难图片框选，帮助 AI 更准确地识别楼道中的人。",
                    purpose="观察 AI 容易数错的画面，并用人工人体框帮助 AI 学习。",
                    participants="刘瀚允",
                    experiment_date=date.today().isoformat(),
                )
                self._refresh_research_choices()
                selected_label = next(label for label, value in self.research_choices.items() if value == experiment_id)
                self.research_var.set(selected_label)
                self.research_box.configure(values=tuple(self.research_choices))
            exported = AIGrowthRecordExporter(self.store).export(
                experiment_id, project_ids, ab_result=self.last_ab_result,
            )
            self.status_var.set(f"研究记录已导出：{exported.docx_path}；统计数据：{exported.xlsx_path}")
            messagebox.showinfo("研究记录已导出", f"已生成 Word 实验记录：\n{exported.docx_path}\n\n已生成 Excel 统计数据：\n{exported.xlsx_path}", parent=self)
        except Exception as error:
            messagebox.showerror("保存研究记录失败", str(error), parent=self)
    def select_challenge_result(self, _event=None):
        selected = self.challenge_tree.selection()
        if not selected:
            return
        feedback, source = self.challenge_rows_by_id[selected[0]]
        self.challenge_detail_var.set(
            f"这是一张没有交给 AI 学习的小测图片。\n\n人工正确人数：{feedback.ground_truth_count} 人\n成长前 AI：{feedback.baseline_count} 人（相差 {feedback.baseline_error:.0f} 人）\n成长后 AI：{feedback.candidate_count} 人（相差 {feedback.candidate_error:.0f} 人）\n\n结论：{feedback.message}"
        )
        self._show_challenge_frame(Path(source["frame_path"]))

    def _show_challenge_frame(self, path: Path):
        import cv2
        from PIL import Image, ImageTk
        frame = cv2.imread(str(path))
        if frame is None:
            return
        height, width = frame.shape[:2]
        scale = min(480 / width, 320 / height)
        shown = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = Image.fromarray(frame[:, :, ::-1]); image.thumbnail(shown)
        self.challenge_photo = ImageTk.PhotoImage(image)
        self.challenge_preview.delete("all")
        self.challenge_preview.create_image((480 - shown[0]) / 2, (320 - shown[1]) / 2, anchor="nw", image=self.challenge_photo)
    def candidate_state(self,state):
        if state == "accepted" and not self.ab_completed:
            messagebox.showwarning("需要真实 A/B", "请先对同一 test split 运行真实 A/B 测试，再人工接受候选模型。", parent=self)
            return
        if hasattr(self,"model_experiment_id"):
            self.store.set_model_candidate_state(self.model_experiment_id,state)
            self.status_var.set("候选模型已" + ("接受，可进入部署。" if state=="accepted" else "放弃，不会部署。"))
    def ssh_check(self):
        try:self.deploy.check_ssh();self.status_var.set("SSH、远端项目、config 与 models 目录检查通过。")
        except DeploymentError as error:messagebox.showerror("SSH 检查失败",str(error),parent=self)
    def ssh_self_check(self):
        try:self.deploy.run_self_check(Path(getattr(self,"candidate_path","")).name);self.status_var.set("远端候选模型自检通过。")
        except Exception as error:messagebox.showerror("自检失败",str(error),parent=self)
    def ssh_deploy(self):
        if not hasattr(self,"candidate_path") or not hasattr(self,"model_experiment_id"):messagebox.showwarning("不能部署","请先导入并接受候选模型。",parent=self);return
        if (self.store.get_model_experiment(self.model_experiment_id)["candidate_state"]!="accepted"):messagebox.showwarning("需要人工接受","请先完成 A/B 并点击“接受候选模型”。",parent=self);return
        try:
            result=self.deploy.deploy_model(self.candidate_path,"huian_person_v1.pt",restart_command=self.restart_var.get()); record=self.store.create_model_deployment(self.model_experiment_id,"huian-pi","/home/x/Huian_YOLO",result.remote_model_path,previous_model_path=result.previous_model_path,previous_config_value=result.rollback_record_path,status="deployed"); self.rollback_var.set(result.rollback_record_path); self.last_deployment_id=record; self.status_var.set(f"部署完成；回滚记录：{result.rollback_record_path}（本地记录 {record}）")
        except Exception as error:messagebox.showerror("部署失败（原模型受保护）",str(error),parent=self)
    def ssh_rollback(self):
        try:
            self.deploy.rollback(self.rollback_var.get().strip(), restart_command=self.restart_var.get())
            if hasattr(self, "last_deployment_id"): self.store.mark_model_deployment_rolled_back(self.last_deployment_id)
            self.status_var.set("已恢复上一模型配置；候选模型文件仍保留，基础 yolov8n.pt 未被覆盖。")
        except Exception as error: messagebox.showerror("回滚失败", str(error), parent=self)
    def on_zoom_changed(self,factor): self._zoom_factor=factor; self._redraw(); self.after_idle(lambda:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
    def close(self): self.closing=True; self.worker.close()
