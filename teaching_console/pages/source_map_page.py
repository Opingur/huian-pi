"""Source navigation page for teacher preparation."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from teaching_console.services.project_inspector import SourceEntry, entry_exists, source_entries


class SourceMapPage(ttk.Frame):
    def __init__(self, master, project_root, open_file, open_directory, copy_path) -> None:
        super().__init__(master, padding=12)
        self.project_root = project_root
        self.open_file, self.open_directory, self.copy_path = open_file, open_directory, copy_path
        self.entries = source_entries(project_root)
        self._entry_by_id: dict[str, SourceEntry] = {}
        self._selected: SourceEntry | None = None
        self._build()

    def _build(self) -> None:
        ttk.Label(self, text="源码地图", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(self, text="点击左侧模块查看真实代码职责；路径会实时检查是否存在。", foreground="#444444").pack(anchor="w", pady=(2, 10))
        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left, right = ttk.Frame(panes, padding=(0, 0, 10, 0)), ttk.Frame(panes, padding=(10, 0, 0, 0))
        panes.add(left, weight=1); panes.add(right, weight=3)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.tree.pack(fill="both", expand=True)
        parents: dict[str, str] = {}
        for entry in self.entries:
            parent = parents.get(entry.category)
            if parent is None:
                parent = self.tree.insert("", "end", text=entry.category, open=True)
                parents[entry.category] = parent
            suffix = "" if entry_exists(self.project_root, entry) else "（未找到）"
            item_id = self.tree.insert(parent, "end", text=entry.title + suffix)
            self._entry_by_id[item_id] = entry
        self.tree.bind("<<TreeviewSelect>>", self._show_selected)
        self.details = tk.Text(right, wrap="word", height=24, state="disabled", font=("Consolas", 10))
        self.details.pack(fill="both", expand=True)
        buttons = ttk.Frame(right)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="打开源码", command=lambda: self._run(self.open_file)).pack(side="left")
        ttk.Button(buttons, text="打开所在目录", command=lambda: self._run(self.open_directory)).pack(side="left", padx=6)
        ttk.Button(buttons, text="复制路径", command=lambda: self._run(self.copy_path)).pack(side="left")
        self._write("请选择左侧具体模块。")

    def _show_selected(self, _event=None) -> None:
        selected = self.tree.selection()
        self._selected = self._entry_by_id.get(selected[0]) if selected else None
        if self._selected is None:
            return
        item = self._selected
        path = self.project_root / item.path
        status = "存在" if path.exists() else "未找到"
        self._write("\n".join((
            f"模块作用\n{item.role}", f"\n文件路径\n{path}\n状态：{status}",
            f"\n关键类\n{item.classes}", f"\n关键函数\n{item.functions}",
            f"\n主要输入\n{item.inputs}", f"\n主要输出\n{item.outputs}",
            f"\n相关配置\n{item.config}", f"\n当前注意事项\n{item.note}",
        )))

    def _write(self, text: str) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _run(self, callback) -> None:
        if self._selected is not None:
            callback(self.project_root / self._selected.path)
