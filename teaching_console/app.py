"""Root Tkinter application for 慧安楼道｜教学与调试台."""
from __future__ import annotations

import os
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from teaching_console.pages.esp32_page import Esp32Page
from teaching_console.pages.overview_page import OverviewPage
from teaching_console.pages.model_optimization_page import ModelOptimizationPage
from teaching_console.pages.source_map_page import SourceMapPage
from teaching_console.pages.trajectory_direction_page import TrajectoryDirectionPage
from teaching_console.pages.trend_crowd_page import TrendCrowdPage
from teaching_console.pages.research_page import ResearchPage
from teaching_console.pages.vision_tracking_page import VisionTrackingPage
from teaching_console.pages.live_system_page import LiveSystemPage
from teaching_console.pages.demo_showcase_page import DemoShowcasePage
from teaching_console.project_paths import check_project, project_root
from teaching_console.services.source_opening import open_source_file, pyinstaller_source_notice
from teaching_console.ui_zoom import ZoomManager


class TeachingConsoleApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.root_path = project_root()
        self.project_check = check_project(self.root_path)
        self.title("慧安楼道｜教学与调试台")
        self.geometry("1200x830")
        self.minsize(960, 620)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.project_status = tk.StringVar()
        self.esp32_status = tk.StringVar(value="ESP32：未连接")
        self.serial_status = tk.StringVar(value="串口：—  波特率：115200")
        self.zoom_status = tk.StringVar()
        self.zoom_manager = ZoomManager(self, self.zoom_status)
        self._build()
        self.zoom_manager.add_callback(self._notify_pages_of_zoom)
        self.zoom_manager.install_event_bindings()
        self.zoom_manager.set_zoom(100)

    def _build(self) -> None:
        status = ttk.Frame(self, padding=(10, 6)); status.pack(side="top", fill="x")
        project_text = "项目目录：正常" if self.project_check.is_valid else "项目目录：异常"
        self.project_status.set(project_text)
        ttk.Label(status, textvariable=self.project_status).pack(side="left")
        ttk.Separator(status, orient="vertical").pack(side="left", fill="y", padx=12)
        ttk.Label(status, textvariable=self.esp32_status).pack(side="left")
        ttk.Separator(status, orient="vertical").pack(side="left", fill="y", padx=12)
        ttk.Label(status, textvariable=self.serial_status).pack(side="left")
        ttk.Separator(status, orient="vertical").pack(side="left", fill="y", padx=12)
        ttk.Label(status, textvariable=self.zoom_status).pack(side="left")
        shell = ttk.Frame(self); shell.pack(fill="both", expand=True)
        nav = ttk.Frame(shell, padding=10); nav.pack(side="left", fill="y")
        ttk.Label(nav, text="导航", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
        content = ttk.Frame(shell); content.pack(side="left", fill="both", expand=True)
        self._visible_page = None
        self.pages = {
            "系统总览": OverviewPage(content, self.root_path),
            "实时系统": LiveSystemPage(content, self.root_path),
            "展示演示": DemoShowcasePage(content, self.root_path),
            "源码地图": SourceMapPage(content, self.root_path, self.open_source, self.open_directory, self.copy_path),
            "YOLO / Tracking": VisionTrackingPage(content, self.root_path, self.open_source, self.copy_path),
            "轨迹 / Direction": TrajectoryDirectionPage(content, self.root_path, self.open_source, self.copy_path),
            "趋势 / Crowd Index": TrendCrowdPage(content, self.root_path, self.open_source, self.copy_path),
            "研究记录 / Ground Truth": ResearchPage(content, self.root_path),
            "模型优化 / YOLO Fine-tune": ModelOptimizationPage(content, self.root_path, self.open_source),
            "ESP32实验": Esp32Page(content, self.connection_changed),
        }
        for title in self.pages:
            ttk.Button(nav, text=title, command=lambda page=title: self.show(page), width=16).pack(fill="x", pady=3)
        ttk.Separator(nav).pack(fill="x", pady=14)
        ttk.Label(nav, text=f"项目根目录\n{self.root_path}", wraplength=190, foreground="#555555").pack(anchor="w")
        self.show("系统总览")

    def show(self, name: str) -> None:
        if self._visible_page is not None:
            callback = getattr(self._visible_page, "on_hide", None)
            if callback is not None: callback()
        for page in self.pages.values(): page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self._visible_page = self.pages[name]
        callback = getattr(self._visible_page, "on_show", None)
        if callback is not None: callback()

    def _notify_pages_of_zoom(self, factor: float) -> None:
        for page in self.pages.values():
            callback = getattr(page, "on_zoom_changed", None)
            if callback is not None:
                callback(factor)

    def connection_changed(self, connected: bool, port: str, baud: int) -> None:
        self.esp32_status.set("ESP32：已连接" if connected else "ESP32：未连接")
        self.serial_status.set(f"串口：{port or '—'}  波特率：{baud}")

    def open_source(self, path: Path, line: int | None = None) -> None:
        result = open_source_file(path, line)
        if not result.opened:
            messagebox.showwarning("无法打开源码", result.message or str(path), parent=self)
            return
        notice = pyinstaller_source_notice()
        if notice:
            messagebox.showinfo("源码打开提示", notice, parent=self)

    def open_directory(self, path: Path) -> None:
        target = path if path.is_dir() else path.parent
        if not target.exists():
            messagebox.showwarning("目录不存在", str(target), parent=self); return
        self._start(target)

    def copy_path(self, path: Path) -> None:
        self.clipboard_clear(); self.clipboard_append(str(path)); self.update()

    def _start(self, path: Path) -> None:
        try:
            if os.name == "nt": os.startfile(str(path))
            else: subprocess.Popen(["xdg-open", str(path)])
        except OSError as error:
            messagebox.showerror("无法打开", str(error), parent=self)

    def _close(self) -> None:
        for page in self.pages.values():
            callback = getattr(page, "close", None)
            if callback is not None:
                callback()
        self.destroy()