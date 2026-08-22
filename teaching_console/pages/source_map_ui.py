"""Two-view, fact-linked teaching Source Map page."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from teaching_console.services.source_map_catalog import (
    COMPATIBLE,
    INACTIVE,
    OFFICIAL,
    SourceEntry,
    engineering_entries,
    entry_exists,
    search_entries,
    teaching_entries,
)


STATUS_LABELS = {
    OFFICIAL: "正式运行",
    COMPATIBLE: "兼容保留",
    "candidate": "候选实现",
    INACTIVE: "停用 / inactive",
}

QUICK_QUESTIONS = (
    ("机器怎么看到画面？", "camera_frame"),
    ("机器怎么找到人？", "yolo_detection"),
    ("为什么同一个人有 Track ID？", "bytetrack_tracking"),
    ("轨迹和方向从哪里来？", "motion_direction"),
    ("为什么会出现 CROWD？", "flow_risk"),
    ("Crowd Index 怎么算？", "crowd_index"),
    ("10/20/30 秒预测是什么？", "prediction"),
    ("树莓派怎样把结果发给 ESP32？", "uart_json"),
    ("MQ-2 和 DHT11 做什么？", "esp32_firmware"),
    ("RGB 灯和蜂鸣器怎么控制？", "esp32_firmware"),
    ("怎样验证系统准不准？", "validation"),
)


class SourceMapPage(ttk.Frame):
    """Keep source navigation practical while making concepts teachable."""

    def __init__(self, master, project_root, open_file, open_directory, copy_path) -> None:
        super().__init__(master, padding=12)
        self.project_root = Path(project_root)
        self.open_file = open_file
        self.open_directory = open_directory
        self.copy_path = copy_path
        self.view_mode = tk.StringVar(value="teaching")
        self.search_text = tk.StringVar()
        self.question_text = tk.StringVar(value="快速问题入口…")
        self._entry_by_item: dict[str, SourceEntry] = {}
        self._item_by_entry_id: dict[str, str] = {}
        self._selected: SourceEntry | None = None
        self._build()
        self._refresh_tree()

    def _build(self) -> None:
        ttk.Label(self, text="源码地图", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            self,
            text="教学视图先讲清概念；工程视图再定位到当前仓库的真实文件、函数与数据流。",
            foreground="#444444",
        ).pack(anchor="w", pady=(2, 8))

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Radiobutton(toolbar, text="教学视图", value="teaching", variable=self.view_mode, command=self._refresh_tree).pack(side="left")
        ttk.Radiobutton(toolbar, text="工程视图", value="engineering", variable=self.view_mode, command=self._refresh_tree).pack(side="left", padx=(8, 18))
        ttk.Label(toolbar, text="搜索：").pack(side="left")
        search = ttk.Entry(toolbar, textvariable=self.search_text, width=24)
        search.pack(side="left")
        search.bind("<KeyRelease>", lambda _event: self._refresh_tree())
        ttk.Button(toolbar, text="清除", command=self._clear_search).pack(side="left", padx=5)
        question = ttk.Combobox(toolbar, textvariable=self.question_text, values=[item[0] for item in QUICK_QUESTIONS], state="readonly", width=25)
        question.pack(side="right")
        question.bind("<<ComboboxSelected>>", self._open_quick_question)
        ttk.Label(toolbar, text="快速问题：").pack(side="right", padx=(0, 4))

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes, padding=(0, 0, 10, 0))
        right = ttk.Frame(panes, padding=(10, 0, 0, 0))
        panes.add(left, weight=2)
        panes.add(right, weight=5)

        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure(OFFICIAL, foreground="#202020")
        self.tree.tag_configure(COMPATIBLE, foreground="#755c1f")
        self.tree.tag_configure("candidate", foreground="#63527c")
        self.tree.tag_configure(INACTIVE, foreground="#777777")
        self.tree.bind("<<TreeviewSelect>>", self._show_selected)

        self.status_line = ttk.Label(right, text="请选择一个知识点或工程节点。")
        self.status_line.pack(anchor="w", pady=(0, 5))
        self.details = tk.Text(right, wrap="word", height=24, state="disabled", font=("Consolas", 10), relief="solid", borderwidth=1)
        self.details.pack(fill="both", expand=True)
        self.links = ttk.Frame(right)
        self.links.pack(fill="x", pady=(7, 0))
        self.actions = ttk.Frame(right)
        self.actions.pack(fill="x", pady=(6, 0))
        ttk.Button(self.actions, text="打开源码", command=self._open_source).pack(side="left")
        ttk.Button(self.actions, text="打开所在目录", command=self._open_directory).pack(side="left", padx=6)
        ttk.Button(self.actions, text="复制路径", command=self._copy_path).pack(side="left")

    def _entries_for_view(self) -> tuple[SourceEntry, ...]:
        teaching = self.view_mode.get() == "teaching"
        return search_entries(self.project_root, self.search_text.get(), teaching=teaching)

    def _refresh_tree(self) -> None:
        selected_id = self._selected.id if self._selected else None
        self.tree.delete(*self.tree.get_children())
        self._entry_by_item.clear()
        self._item_by_entry_id.clear()
        parents: dict[str, str] = {}
        for entry in self._entries_for_view():
            parent = parents.get(entry.category)
            if parent is None:
                parent = self.tree.insert("", "end", text=entry.category, open=True)
                parents[entry.category] = parent
            exists = entry_exists(self.project_root, entry)
            suffix = "" if exists else "（未找到）"
            prefix = "" if self.view_mode.get() == "teaching" else f"[{STATUS_LABELS[entry.status]}] "
            item = self.tree.insert(parent, "end", text=f"{prefix}{entry.title}{suffix}", tags=(entry.status,))
            self._entry_by_item[item] = entry
            self._item_by_entry_id.setdefault(entry.id, item)
        if selected_id in self._item_by_entry_id:
            item = self._item_by_entry_id[selected_id]
            self.tree.selection_set(item)
            self.tree.focus(item)

    def _clear_search(self) -> None:
        self.search_text.set("")
        self._refresh_tree()

    def _open_quick_question(self, _event=None) -> None:
        question = self.question_text.get()
        entry_id = next((target for text, target in QUICK_QUESTIONS if text == question), None)
        if entry_id:
            self._jump_to_engineering(entry_id)

    def _show_selected(self, _event=None) -> None:
        selected = self.tree.selection()
        self._selected = self._entry_by_item.get(selected[0]) if selected else None
        if self._selected is None:
            return
        item = self._selected
        source_path = self.project_root / item.path
        exists = entry_exists(self.project_root, item)
        status = STATUS_LABELS[item.status]
        file_status = "已核验存在" if exists else "当前仓库未找到"
        mode = "教学" if self.view_mode.get() == "teaching" else "工程"
        self.status_line.configure(text=f"{mode}节点 · {status} · {file_status}")
        self._write_details(item, source_path, status, file_status)
        self._rebuild_link_buttons(item)

    def _write_details(self, item: SourceEntry, source_path: Path, status: str, file_status: str) -> None:
        upstream = item.lesson_upstream or self._names_for(item.upstream)
        downstream = item.lesson_downstream or self._names_for(item.downstream)
        lesson = self._lesson_for(item.id)
        if item.teaching_file == "待接入":
            experiment = "实验名称：待接入\n教学文件：待接入\n预计运行方式：待接入\n成功时应该看到什么：待接入"
        else:
            example_path = self.project_root / item.teaching_file
            example_status = "已接入" if example_path.is_file() else "待接入"
            experiment = f"实验名称：{Path(item.teaching_file).stem}\n教学文件：{example_path}\n状态：{example_status}\n预计运行方式：python {item.teaching_file}\n成功时应该看到什么：观察本节的单一现象。"
        text = "\n".join((
            "A. 今天要解决的问题", item.question or item.title,
            "\nB. 一句话解释", item.summary or item.role,
            "\nC. 教学小实验", experiment,
            "\nD. 关键概念", "、".join(item.concepts or item.keywords[:5]) or "—",
            "\nE. 正式项目源码", f"真实文件路径：{source_path}\n真实类：{item.classes}\n真实函数：{item.functions}\n推荐起始行：{item.source_line}\n状态：{status}（{file_status}）\n课次标签：{lesson}",
            "\nF. 主要输入", item.inputs,
            "\nG. 主要输出", item.outputs,
            "\nH. 上一个模块", upstream,
            "\nI. 下一个模块", downstream,
            "\nJ. 相关配置", item.config,
            "\nK. 课堂上只需要看哪几行", f"从 {item.path} 的第 {item.source_line} 行附近开始，看：{item.functions}。",
            "\nL. 容易讲错的地方", item.note,
        ))
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")
    @staticmethod
    def _lesson_for(entry_id: str) -> str:
        if entry_id in {"camera_frame", "yolo_detection"}:
            return "D1"
        if entry_id in {"bytetrack_tracking", "trajectory_history", "motion_direction", "flow_groups"}:
            return "D2-D3"
        if entry_id in {"people_flow", "flow_risk", "crowd_index", "prediction", "vision_risk"}:
            return "D4"
        if entry_id == "esp32_firmware":
            return "D5"
        if entry_id == "uart_json":
            return "D6"
        if entry_id == "validation":
            return "D7"
        return "—"
    def _names_for(self, identifiers: tuple[str, ...]) -> str:
        entries = {entry.id: entry for entry in engineering_entries(self.project_root)}
        return "、".join(entries[item].title for item in identifiers if item in entries) or "—"

    def _rebuild_link_buttons(self, item: SourceEntry) -> None:
        for child in self.links.winfo_children():
            child.destroy()
        if not item.upstream and not item.downstream:
            return
        ttk.Label(self.links, text="关联节点：").pack(side="left")
        entries = {entry.id: entry for entry in engineering_entries(self.project_root)}
        for label, identifiers in (("上游", item.upstream), ("下游", item.downstream)):
            for identifier in identifiers:
                target = entries.get(identifier)
                if target is not None:
                    ttk.Button(self.links, text=f"{label}：{target.title}", command=lambda value=identifier: self._jump_to_engineering(value)).pack(side="left", padx=(0, 4))

    def _jump_to_engineering(self, entry_id: str) -> None:
        self.search_text.set("")
        self.view_mode.set("engineering")
        self._refresh_tree()
        item = self._item_by_entry_id.get(entry_id)
        if item:
            self.tree.selection_set(item)
            self.tree.focus(item)
            self.tree.see(item)
            self._show_selected()

    def _open_source(self) -> None:
        if self._selected is None:
            return
        path = self.project_root / self._selected.path
        try:
            self.open_file(path, self._selected.source_line)
        except TypeError:
            self.open_file(path)

    def _open_directory(self) -> None:
        if self._selected is not None:
            self.open_directory(self.project_root / self._selected.path)

    def _copy_path(self) -> None:
        if self._selected is not None:
            self.copy_path(self.project_root / self._selected.path)

    def on_zoom_changed(self, factor: float) -> None:
        """Refresh the tree row height after the app-wide zoom manager updates fonts."""
        row_height = max(20, int(24 * factor))
        ttk.Style(self).configure("Treeview", rowheight=row_height)
