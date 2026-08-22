"""Display-only zoom support shared by the teaching console pages."""
from __future__ import annotations

from collections.abc import Callable
import tkinter.font as tkfont
from tkinter import ttk


MIN_ZOOM_PERCENT = 70
MAX_ZOOM_PERCENT = 160
DEFAULT_ZOOM_PERCENT = 100
ZOOM_STEP_PERCENT = 10
CONTROL_MASK = 0x0004


def scaled_value(base_value: int, factor: float, minimum: int = 1) -> int:
    """Scale a base display value without accumulating previous zoom rounds."""
    return max(minimum, round(base_value * factor))


class ZoomManager:
    """Own global zoom state and notify existing page instances about redraws."""

    def __init__(self, root=None, status_var=None) -> None:
        self.root = root
        self.status_var = status_var
        self.zoom_percent = DEFAULT_ZOOM_PERCENT
        self._callbacks: list[Callable[[float], None]] = []
        self._base_named_fonts: dict[str, dict] = {}
        self._base_widget_fonts: dict[str, tuple[object, dict]] = {}
        self._widget_font_refs: dict[str, tkfont.Font] = {}
        self._style = None
        self._event_tag = f"TeachingConsoleZoom_{id(self)}"
        if self.root is not None:
            self._style = ttk.Style(self.root)
            self._capture_named_fonts()
        self._update_status()

    @property
    def zoom_factor(self) -> float:
        return self.zoom_percent / 100.0

    def get_zoom_factor(self) -> float:
        return self.zoom_factor

    def add_callback(self, callback: Callable[[float], None]) -> None:
        self._callbacks.append(callback)

    def install_event_bindings(self) -> None:
        """Put Ctrl zoom before individual widget/class wheel bindings."""
        if self.root is None:
            return
        self.root.bind_class(self._event_tag, "<Control-MouseWheel>", self.handle_ctrl_mousewheel)
        self.root.bind_class(self._event_tag, "<Control-0>", self.handle_ctrl_zero)
        for widget in self._walk_widgets(self.root):
            try:
                tags = widget.bindtags()
                if self._event_tag not in tags:
                    widget.bindtags((self._event_tag, *tags))
            except Exception:
                continue

    def zoom_in(self) -> int:
        return self.set_zoom(self.zoom_percent + ZOOM_STEP_PERCENT)

    def zoom_out(self) -> int:
        return self.set_zoom(self.zoom_percent - ZOOM_STEP_PERCENT)

    def reset_zoom(self) -> int:
        return self.set_zoom(DEFAULT_ZOOM_PERCENT)

    def set_zoom(self, percent: int | float) -> int:
        self.zoom_percent = max(MIN_ZOOM_PERCENT, min(MAX_ZOOM_PERCENT, int(percent)))
        self._update_status()
        if self.root is not None:
            self._apply_fonts_and_styles()
        for callback in tuple(self._callbacks):
            callback(self.zoom_factor)
        if self.root is not None:
            self.root.update_idletasks()
        return self.zoom_percent

    def handle_ctrl_mousewheel(self, event):
        """Handle Ctrl+wheel only; ordinary wheel events stay with page scrolling."""
        if not event.state & CONTROL_MASK:
            return None
        if event.delta > 0:
            self.zoom_in()
        elif event.delta < 0:
            self.zoom_out()
        return "break"

    def handle_ctrl_zero(self, _event=None):
        self.reset_zoom()
        return "break"

    def _update_status(self) -> None:
        if self.status_var is not None:
            self.status_var.set(f"缩放：{self.zoom_percent}%")

    def _capture_named_fonts(self) -> None:
        for name in (
            "TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont",
            "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont",
            "TkTooltipFont",
        ):
            try:
                self._base_named_fonts[name] = tkfont.nametofont(name, root=self.root).actual()
            except Exception:
                continue

    def _walk_widgets(self, widget):
        yield widget
        for child in widget.winfo_children():
            yield from self._walk_widgets(child)

    def _capture_explicit_widget_fonts(self) -> None:
        named = set(self._base_named_fonts)
        for widget in self._walk_widgets(self.root):
            key = str(widget)
            if key in self._base_widget_fonts:
                continue
            try:
                font_spec = widget.cget("font")
            except Exception:
                continue
            if not font_spec or str(font_spec) in named:
                continue
            try:
                self._base_widget_fonts[key] = (
                    widget,
                    tkfont.Font(root=self.root, font=font_spec).actual(),
                )
            except Exception:
                continue

    def _scaled_font(self, actual: dict) -> tkfont.Font:
        options = {
            key: actual[key]
            for key in ("family", "weight", "slant", "underline", "overstrike")
            if key in actual
        }
        base_size = int(actual.get("size", 10))
        sign = -1 if base_size < 0 else 1
        options["size"] = sign * max(7, round(abs(base_size) * self.zoom_factor))
        return tkfont.Font(root=self.root, **options)

    def _apply_fonts_and_styles(self) -> None:
        for name, actual in self._base_named_fonts.items():
            try:
                tkfont.nametofont(name, root=self.root).configure(
                    size=max(7, round(abs(int(actual.get("size", 10))) * self.zoom_factor))
                )
            except Exception:
                continue
        self._capture_explicit_widget_fonts()
        for key, (widget, actual) in tuple(self._base_widget_fonts.items()):
            try:
                if not widget.winfo_exists():
                    self._base_widget_fonts.pop(key, None)
                    self._widget_font_refs.pop(key, None)
                    continue
                font = self._scaled_font(actual)
                widget.configure(font=font)
                self._widget_font_refs[key] = font
            except Exception:
                continue
        if self._style is not None:
            factor = self.zoom_factor
            self._style.configure("Treeview", rowheight=scaled_value(22, factor))
            self._style.configure(
                "TButton",
                padding=(scaled_value(6, factor), scaled_value(2, factor)),
            )
