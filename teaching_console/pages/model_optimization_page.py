"""Eight-stage YOLO fine-tune teaching workflow (UI only; no local training)."""
from __future__ import annotations

import csv
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import webbrowser

from teaching_console.runtime_paths import ensure_writable_data_root
from teaching_console.services.model_deployment_service import DeploymentError, ModelDeploymentService
from teaching_console.services.model_optimization_service import (
    ABComparisonService, BoundingBox, CandidateModelManager, CanvasImageTransform,
    ColabPackageBuilder, DatasetBuilder,
)
from teaching_console.services.model_optimization_vision_service import ModelOptimizationVisionService
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
        self.worker = VisionTeachingWorker(ModelOptimizationVisionService(self.root_path))
        self.deploy = ModelDeploymentService()
        self.token = 0; self.busy = False; self.closing = False; self.video = None; self.ab_completed = False
        self.project_id = None; self.frame_rows = []; self.current_frame = None
        self.raw_frame = None; self.boxes: list[BoundingBox] = []; self.system_boxes: list[BoundingBox] = []
        self.undo: list[list[BoundingBox]] = []; self.selected = None; self.drag = None; self.transform = None
        self.photo = None; self._zoom_factor = 1.0
        self.video_var = tk.StringVar(value="未选择视频")
        self.status_var = tk.StringVar(value="准备就绪：本机只准备数据，不训练。")
        self.dataset_var = tk.StringVar(value="当前数据集：未建立（默认 huian_person_v1）")
        self.candidate_var = tk.StringVar(value="候选模型：未导入")
        self.limit_var = tk.StringVar(value="25"); self.split_var = tk.StringVar(value="train")
        self.show_system_var = tk.BooleanVar(value=False); self.restart_var = tk.StringVar(value="")
        self._scroll(); self._build(); self.after(40, self._drain)

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
        ttk.Label(self.body, text="模型优化 / YOLO Fine-tune", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(self.body, text=f"基础模型：{self.config.model_path.relative_to(self.root_path)}    训练平台：Google Colab GPU", wraplength=1050).pack(anchor="w")
        ttk.Label(self.body, textvariable=self.dataset_var, foreground="#555555").pack(anchor="w")
        ttk.Label(self.body, textvariable=self.candidate_var, foreground="#555555").pack(anchor="w")
        ttk.Label(self.body, text="人数 Ground Truth 是人工人数；Detection Ground Truth 是人工人体框。调 confidence 不等于训练模型。灰度 / 低颜色信息、高位俯拍、遮挡严重是本模块的困难视觉场景。", wraplength=1050, foreground="#665500").pack(anchor="w", pady=(4, 8))
        self.tabs = ttk.Notebook(self.body); self.tabs.pack(fill="both", expand=True)
        self.stage1 = self._tab("1. 基线测试"); self.stage2 = self._tab("2. 困难帧筛选"); self.stage3 = self._tab("3. Detection Ground Truth")
        self.stage4 = self._tab("4. 数据集构建与检查"); self.stage5 = self._tab("5. 生成 Colab 训练包"); self.stage6 = self._tab("6. 导入训练结果")
        self.stage7 = self._tab("7. 独立测试 / A-B 对比"); self.stage8 = self._tab("8. SSH 部署树莓派")
        self._baseline(); self._hard_frames(); self._annotation(); self._dataset(); self._colab(); self._import(); self._ab(); self._deploy()
        ttk.Label(self.body, textvariable=self.status_var, wraplength=1050, foreground="#444444").pack(anchor="w", pady=(8, 0))

    def _tab(self, title):
        page = ttk.Frame(self.tabs, padding=10); self.tabs.add(page, text=title); return page

    def _baseline(self):
        ttk.Label(self.stage1, text="基线测试使用未参与训练的 test split 标注帧，以 models/yolov8n.pt 作为固定对照。A/B 阶段会在同一组人工框上真实计算人数和 IoU 指标。", wraplength=1000).pack(anchor="w")
        ttk.Button(self.stage1, text="打开 YOLO 检测源码", command=lambda: self.open_source(self.root_path / "rpi_app/vision/detector.py", 12)).pack(anchor="w", pady=8)

    def _hard_frames(self):
        top = ttk.Frame(self.stage2); top.pack(fill="x")
        ttk.Button(top, text="选择视频", command=self.choose_video).pack(side="left")
        ttk.Label(top, text="视频级划分：").pack(side="left", padx=(12, 0))
        ttk.Combobox(top, textvariable=self.split_var, values=("train", "val", "test"), width=8, state="readonly").pack(side="left")
        ttk.Label(top, text="候选数量（5–25）：").pack(side="left", padx=(12, 0)); ttk.Entry(top, textvariable=self.limit_var, width=5).pack(side="left")
        ttk.Button(top, text="分析困难帧", command=self.analyze).pack(side="left", padx=6)
        ttk.Button(top, text="打开源码", command=lambda: self.open_source(self.root_path / "teaching_console/services/model_optimization_vision_service.py", 1)).pack(side="left")
        ttk.Label(self.stage2, textvariable=self.video_var, wraplength=1000).pack(anchor="w", pady=6)
        columns = ("frame", "time", "count", "confidence", "reason")
        self.frame_tree = ttk.Treeview(self.stage2, columns=columns, show="headings", height=12)
        for key, label, width in (("frame", "帧号", 70), ("time", "时间", 80), ("count", "系统人数", 80), ("confidence", "平均/最低 confidence", 150), ("reason", "推荐原因", 520)):
            self.frame_tree.heading(key, text=label); self.frame_tree.column(key, width=width, anchor="w")
        self.frame_tree.pack(fill="both", expand=True); self.frame_tree.bind("<<TreeviewSelect>>", self.select_frame)
        actions = ttk.Frame(self.stage2); actions.pack(anchor="w", pady=6)
        ttk.Button(actions, text="保留", command=lambda: self.set_kept(True)).pack(side="left"); ttk.Button(actions, text="跳过", command=lambda: self.set_kept(False)).pack(side="left", padx=5)
        self.preview = tk.Canvas(self.stage2, width=360, height=240, background="#202020", highlightthickness=1, highlightbackground="#999999")
        self.preview.pack(anchor="w", pady=(4, 0))
        ttk.Label(self.stage2, text="选中候选帧后预览原始画面。筛选最多 25 帧；真实检测结果按人数、低置信度、人数跳变等启发式指标评分，并做时间间隔去重。", foreground="#555555").pack(anchor="w")

    def _annotation(self):
        ttk.Label(self.stage3, text="左键空白处拖动新建 person 框；点击框选择，拖动内部移动，拖动边缘/四角调整。保存坐标始终是原始视频分辨率，不是 Canvas 坐标。", wraplength=1000).pack(anchor="w")
        controls = ttk.Frame(self.stage3); controls.pack(fill="x", pady=6)
        ttk.Button(controls, text="上一帧", command=lambda: self.move_frame(-1)).pack(side="left"); ttk.Button(controls, text="保存", command=self.save_boxes).pack(side="left", padx=4); ttk.Button(controls, text="保存并下一帧", command=lambda: (self.save_boxes(), self.move_frame(1))).pack(side="left")
        ttk.Checkbutton(controls, text="显示原 YOLO 检测框", variable=self.show_system_var, command=self.toggle_system).pack(side="left", padx=12)
        ttk.Button(controls, text="撤销", command=self.undo_box).pack(side="left"); ttk.Label(controls, text="Delete 删除选中框；Ctrl+Z 撤销").pack(side="left", padx=8)
        self.annotation_info = tk.StringVar(value="当前帧：—")
        ttk.Label(self.stage3, textvariable=self.annotation_info).pack(anchor="w")
        self.draw = tk.Canvas(self.stage3, width=BASE_VIEW_SIZE[0], height=BASE_VIEW_SIZE[1], background="#202020", highlightthickness=1, highlightbackground="#999999")
        self.draw.pack(anchor="w", pady=6); self.draw.bind("<ButtonPress-1>", self.press); self.draw.bind("<B1-Motion>", self.motion); self.draw.bind("<ButtonRelease-1>", self.release); self.draw.bind("<Delete>", lambda _e: self.delete_box()); self.draw.bind("<Control-z>", lambda _e: self.undo_box())
        ttk.Label(self.stage3, text="标注规范：框贴近当前可见人体；多人分别标框；不包含大面积背景；部分遮挡保持统一原则；不要猜测完全不可见区域。", wraplength=1000, foreground="#665500").pack(anchor="w")

    def _dataset(self):
        ttk.Label(self.stage4, text="按完整 source_video 划分 train / val / test，禁止同一视频的相邻帧跨集合。会导出 Ultralytics 标准 images、labels、data.yaml、metadata.json。", wraplength=1000).pack(anchor="w")
        ttk.Button(self.stage4, text="生成 huian_person_v1 数据集", command=self.build_dataset).pack(anchor="w", pady=8)
        ttk.Button(self.stage4, text="打开数据集导出源码", command=lambda: self.open_source(self.root_path / "teaching_console/services/model_optimization_service.py", 184)).pack(anchor="w")

    def _colab(self):
        ttk.Label(self.stage5, text="本机不训练。生成包含 dataset.zip、真实可编辑 train.py、中文 train_colab.ipynb、data.yaml、experiment.json 和 README.md 的 Colab 训练包。默认 Epoch=50、imgsz=640、基础模型 yolov8n.pt。", wraplength=1000).pack(anchor="w")
        row = ttk.Frame(self.stage5); row.pack(anchor="w", pady=8)
        ttk.Button(row, text="生成 Colab 训练包", command=self.build_package).pack(side="left"); ttk.Button(row, text="打开 Colab", command=lambda: webbrowser.open("https://colab.research.google.com/")).pack(side="left", padx=6); ttk.Button(row, text="打开训练源码", command=lambda: self.open_source(self.root_path / "training/train.py", 1)).pack(side="left")
        ttk.Label(self.stage5, text="操作：登录 Google → 打开生成的 notebook → 选择 GPU Runtime → 上传 dataset.zip → 按中文单元格运行 → 下载 best.pt。", wraplength=1000).pack(anchor="w")

    def _import(self):
        ttk.Label(self.stage6, text="从 Colab 选择 best.pt；它会复制到可写目录的 models/experiments/huian_person_v1/best.pt，绝不覆盖基础 models/yolov8n.pt。", wraplength=1000).pack(anchor="w")
        ttk.Button(self.stage6, text="导入 best.pt", command=self.import_candidate).pack(anchor="w", pady=8)

    def _ab(self):
        ttk.Label(self.stage7, text="仅使用 test split 未参与训练的人工框。原 YOLOv8n 与候选模型在完全相同的 Ground Truth 上比较 Precision、Recall、人数 MAE、最大人数误差和 exact count rate；mAP 若未可靠运行 Ultralytics validation 则明确为未计算。", wraplength=1000).pack(anchor="w")
        ttk.Button(self.stage7, text="运行独立 A/B 测试", command=self.run_ab).pack(anchor="w", pady=8)
        self.ab_var = tk.StringVar(value="尚未运行 A/B。")
        ttk.Label(self.stage7, textvariable=self.ab_var, wraplength=1000).pack(anchor="w")
        row = ttk.Frame(self.stage7); row.pack(anchor="w", pady=8); ttk.Button(row, text="接受候选模型", command=lambda: self.candidate_state("accepted")).pack(side="left"); ttk.Button(row, text="放弃候选模型", command=lambda: self.candidate_state("rejected")).pack(side="left", padx=6)

    def _deploy(self):
        ttk.Label(self.stage8, text="目标设备：huian-pi    远端项目：/home/x/Huian_YOLO。部署只上传独立候选文件并备份远端 config.json；失败自动回滚，不删除也不覆盖 yolov8n.pt。", wraplength=1000).pack(anchor="w")
        self.rollback_var = tk.StringVar(value="")
        row = ttk.Frame(self.stage8); row.pack(anchor="w", pady=8); ttk.Button(row, text="测试 SSH", command=self.ssh_check).pack(side="left"); ttk.Button(row, text="运行自检", command=self.ssh_self_check).pack(side="left", padx=5); ttk.Button(row, text="部署模型", command=self.ssh_deploy).pack(side="left"); ttk.Button(row, text="回滚上一模型", command=self.ssh_rollback).pack(side="left", padx=5)
        ttk.Label(self.stage8, text="已核实的重启命令（必填，不会猜测）：").pack(anchor="w"); ttk.Entry(self.stage8, textvariable=self.restart_var, width=70).pack(anchor="w")
        ttk.Label(self.stage8, text="远端回滚记录（部署成功后自动填入）：").pack(anchor="w", pady=(6, 0)); ttk.Entry(self.stage8, textvariable=self.rollback_var, width=85).pack(anchor="w")

    def choose_video(self):
        path = filedialog.askopenfilename(parent=self, filetypes=(("视频", "*.mp4 *.avi *.mov *.mkv"),))
        if path: self._send("open_video", Path(path)); self.status_var.set("正在打开视频…")

    def analyze(self):
        try: limit = int(self.limit_var.get()); assert 5 <= limit <= 25
        except Exception: messagebox.showwarning("输入错误", "候选数量必须是 5 到 25。", parent=self); return
        if self.video is None: messagebox.showwarning("请先选择视频", "请选择原始输入视频。", parent=self); return
        self._send("analyze_difficult_frames", limit); self.status_var.set("正在使用真实 PersonDetector 分析困难帧…")

    def _send(self, operation, *args): self.token += 1; self.busy = True; self.worker.submit(self.token, operation, *args)
    def _drain(self):
        if self.closing: return
        try:
            while True:
                result = self.worker.results.get_nowait()
                if result.token != self.token: continue
                self.busy = False
                if result.error: self.status_var.set("错误：" + result.error); continue
                self._handle(result.operation, result.value)
        except queue.Empty: pass
        self.after(40, self._drain)

    def _handle(self, operation, value):
        if operation == "open_video":
            self.video = value; self.video_var.set(f"视频：{value.path} | {value.width}×{value.height} | {value.fps:.2f} FPS")
            self.status_var.set("视频已打开；可开始筛选困难帧。")
        elif operation == "analyze_difficult_frames": self._save_recommendations(value)
        elif operation == "read_raw": self._show_raw(value)
        elif operation == "detect": self.system_boxes = [BoundingBox(*row.bbox) for row in value.rows]; self._redraw()

    def _save_recommendations(self, recommendations):
        source = str(self.video.path)
        existing = next((project for project in self.store.list_detection_annotation_projects("huian_person_v1") if project["source_video"] == source and project["split_name"] == self.split_var.get()), None)
        if existing is None:
            self.project_id = self.store.create_detection_annotation_project(Path(source).stem + "_detection", source, self.split_var.get(), "huian_person_v1")
        else:
            self.project_id = existing["id"]
        current = self.store.detection_frame_annotations(self.project_id)
        known_frames = {row["frame_index"] for row in current}
        for item in recommendations:
            if item.frame_index not in known_frames:
                self.store.create_detection_frame_annotation(self.project_id, item.frame_index, item.time_seconds, self.video.width, self.video.height, system_count=item.system_count, average_confidence=item.average_confidence, minimum_confidence=item.minimum_confidence, recommendation_reasons="；".join(item.reasons))
        self.frame_rows = self.store.detection_frame_annotations(self.project_id)
        self._refresh_frames()
        self.status_var.set(f"已载入 {len(self.frame_rows)} 个候选帧；同一视频与划分会恢复既有人工框，不重复创建项目。")
    def _refresh_frames(self):
        self.frame_tree.delete(*self.frame_tree.get_children())
        for row in self.frame_rows:
            confidence = "—" if row["average_confidence"] is None else f"{row['average_confidence']:.2f} / {row['minimum_confidence']:.2f}"
            mark = "保留" if row["kept"] else "跳过"
            self.frame_tree.insert("", "end", iid=row["id"], values=(row["frame_index"], f"{row['video_time_seconds']:.2f}s", row["system_count"], confidence, f"[{mark}] {row['recommendation_reasons']}"))

    def select_frame(self, _event=None):
        selected = self.frame_tree.selection()
        if not selected or self.busy: return
        self.current_frame = self.store.get_detection_frame_annotation(selected[0]); self.boxes = [BoundingBox(row["x1"], row["y1"], row["x2"], row["y2"]) for row in self.store.detection_person_boxes(selected[0])]; self.undo = []; self.system_boxes = []
        self._send("read_raw", self.current_frame["frame_index"])

    def set_kept(self, kept):
        if self.current_frame is None: return
        self.store.update_detection_frame_annotation(self.current_frame["id"], kept=kept); self.frame_rows = self.store.detection_frame_annotations(self.project_id); self._refresh_frames()

    def _show_raw(self, packet):
        self.raw_frame = packet.frame_bgr; self._save_raw_frame(); self._redraw(); self._redraw_preview()

    def _redraw_preview(self):
        if not hasattr(self, "preview") or self.raw_frame is None:
            return
        from PIL import Image, ImageTk
        height, width = self.raw_frame.shape[:2]
        scale = min(360 / width, 240 / height)
        shown = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = Image.fromarray(self.raw_frame[:, :, ::-1])
        image.thumbnail(shown)
        self.preview_photo = ImageTk.PhotoImage(image)
        self.preview.delete("all")
        self.preview.create_image((360 - shown[0]) / 2, (240 - shown[1]) / 2, anchor="nw", image=self.preview_photo)
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
        if self.current_frame is not None: self.store.replace_detection_person_boxes(self.current_frame["id"], [dict(x1=b.x1,y1=b.y1,x2=b.x2,y2=b.y2,class_id=0) for b in self.boxes]); self.status_var.set("已保存原始坐标 person Bounding Box。")
    def move_frame(self, direction):
        if self.current_frame is None: return
        kept = [row for row in self.frame_rows if row["kept"]]; index = next((i for i,row in enumerate(kept) if row["id"] == self.current_frame["id"]), 0); target = kept[max(0, min(len(kept)-1, index+direction))] if kept else None
        if target: self.frame_tree.selection_set(target["id"]); self.select_frame()
    def toggle_system(self):
        if self.show_system_var.get() and self.current_frame is not None: self._send("detect", self.current_frame["frame_index"])
        else: self._redraw()

    def _dataset_rows(self):
        projects = self.store.list_detection_annotation_projects("huian_person_v1"); assignments = self.store.validate_detection_dataset_splits("huian_person_v1"); rows=[]
        for project in projects:
            for frame in self.store.detection_frame_annotations(project["id"], include_skipped=False):
                if not frame["image_path"]: continue
                rows.append({"source_video":frame["source_video"],"frame_path":frame["image_path"],"frame_index":frame["frame_index"],"image_width":frame["image_width"],"image_height":frame["image_height"],"boxes":[BoundingBox(box["x1"],box["y1"],box["x2"],box["y2"]) for box in self.store.detection_person_boxes(frame["id"])]})
        return rows, assignments
    def build_dataset(self):
        try:
            rows, assignments = self._dataset_rows(); result = DatasetBuilder(self.data_root).build("huian_person_v1", rows, assignments); self.dataset_var.set(f"当前数据集：huian_person_v1（{result.frame_count} 帧，{result.annotation_count} 人体框）"); self.status_var.set(f"数据集已生成：{result.dataset_dir}")
        except Exception as error: messagebox.showerror("数据集构建失败", str(error), parent=self)
    def build_package(self):
        try:
            package = ColabPackageBuilder(self.data_root, template_root=self.root_path).build(self.data_root/"datasets"/"huian_person_v1", "huian_person_v1"); self.model_experiment_id = self.store.create_model_experiment("huian_person_v1", "huian_person_v1", self.config.model_path, epochs=50, imgsz=640, training_package_path=package.package_dir); self.status_var.set(f"Colab 训练包已生成：{package.package_dir}")
        except Exception as error: messagebox.showerror("生成训练包失败", str(error), parent=self)
    def import_candidate(self):
        source = filedialog.askopenfilename(parent=self, title="选择 Colab 下载的 best.pt", filetypes=(("PyTorch 模型","*.pt"),))
        if not source: return
        try:
            candidate = CandidateModelManager(self.data_root, baseline_model_path=self.config.model_path).import_best_pt("huian_person_v1", Path(source)); self.candidate_path = candidate.model_path; self.candidate_var.set(f"候选模型：{candidate.model_path}")
            if not hasattr(self,"model_experiment_id"): self.model_experiment_id = self.store.create_model_experiment("huian_person_v1", "huian_person_v1", self.config.model_path)
            self.store.set_model_candidate(self.model_experiment_id, candidate.model_path, result_metadata_path=candidate.metadata_path); self.status_var.set("候选 best.pt 已导入；请先做 A/B，再人工接受。")
        except Exception as error: messagebox.showerror("导入失败",str(error),parent=self)
    def run_ab(self):
        if not hasattr(self,"candidate_path"): messagebox.showwarning("缺少候选模型","请先导入 best.pt。",parent=self); return
        try:
            from rpi_app.vision.detector import PersonDetector
            import cv2
            rows, assignments = self._dataset_rows(); test=[row for row in rows if assignments[row["source_video"]] == "test"]
            if not test: raise ValueError("没有可用的 test split 人工标注帧。")
            base, candidate = PersonDetector(self.config.model_path,self.config.confidence), PersonDetector(self.candidate_path,self.config.confidence); gt=[]; bp={}; cp={}
            for row in test:
                image=cv2.imread(str(row["frame_path"])); key=f"{row['source_video']}:{row['frame_index']}"; gt.append({"frame_id":key,"boxes":row["boxes"]}); bp[key]=[BoundingBox(item["x1"],item["y1"],item["x2"],item["y2"]) for item in base.detect(image)]; cp[key]=[BoundingBox(item["x1"],item["y1"],item["x2"],item["y2"]) for item in candidate.detect(image)]
            result=ABComparisonService().compare(gt,bp,cp)
            out=self.data_root/"validation"/"exports"/"model_optimization"; out.mkdir(parents=True,exist_ok=True)
            stem="baseline_vs_huian_person_v1"
            (out/(stem+".json")).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            by_key = {f"{row['source_video']}:{row['frame_index']}": row for row in test}
            fields = ("sample","video","frame_index","ground_truth_count","baseline_count","candidate_count","baseline_error","candidate_error","baseline_tp","baseline_fp","baseline_fn","candidate_tp","candidate_fp","candidate_fn")
            with (out/(stem+".csv")).open("w",newline="",encoding="utf-8") as handle:
                writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader()
                for index, sample in enumerate(result["samples"], start=1):
                    source = by_key[sample["frame_id"]]
                    baseline_metrics, candidate_metrics = sample["baseline"], sample["candidate"]
                    writer.writerow({"sample": index, "video": source["source_video"], "frame_index": source["frame_index"], "ground_truth_count": sample["ground_truth_count"], "baseline_count": baseline_metrics["model_count"], "candidate_count": candidate_metrics["model_count"], "baseline_error": baseline_metrics["absolute_count_error"], "candidate_error": candidate_metrics["absolute_count_error"], "baseline_tp": baseline_metrics["true_positives"], "baseline_fp": baseline_metrics["false_positives"], "baseline_fn": baseline_metrics["false_negatives"], "candidate_tp": candidate_metrics["true_positives"], "candidate_fp": candidate_metrics["false_positives"], "candidate_fn": candidate_metrics["false_negatives"]})
            self.ab_var.set("原模型：MAE %.3f，Precision %s，Recall %s；候选：MAE %.3f，Precision %s，Recall %s。mAP：未计算。"%(result["baseline"]["count_mae"],result["baseline"]["precision"],result["baseline"]["recall"],result["candidate"]["count_mae"],result["candidate"]["precision"],result["candidate"]["recall"]))
            self.ab_completed = True
            self.status_var.set(f"A/B 真实逐样本结果已导出：{out}")
        except Exception as error: messagebox.showerror("A/B 测试失败",str(error),parent=self)
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
