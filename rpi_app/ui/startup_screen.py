"""Fullscreen startup and fatal-error screen for the formal camera deployment."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


STARTUP_WIDTH = 1280
STARTUP_HEIGHT = 1024

STARTUP_TITLE = "慧安安全监测系统"
STARTUP_INITIALIZING = "系统初始化中……"

STARTUP_TITLE_SIZE = 68
STARTUP_STATUS_SIZE = 40

STARTUP_TITLE_CENTER_Y = 440
STARTUP_STATUS_CENTER_Y = 535

DEFAULT_BOLD_FONT = (
    "/usr/share/fonts/opentype/noto/"
    "NotoSansCJK-Bold.ttc"
)


def _resolve_font(font_path: str | None) -> str:
    # Splash 优先使用粗体；如果系统粗体不存在，再退回配置字体。
    if Path(DEFAULT_BOLD_FONT).exists():
        return DEFAULT_BOLD_FONT

    if font_path and Path(font_path).exists():
        return font_path

    raise RuntimeError("startup Chinese font not found")


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    center_y: int,
    fill: tuple[int, int, int],
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (STARTUP_WIDTH - text_width) // 2
    y = int(center_y - text_height / 2 - bbox[1])

    draw.text(
        (x, y),
        text,
        font=font,
        fill=fill,
    )


def startup_entries(
    status_text: str,
    error: bool = False,
) -> list[tuple[tuple[int, int], str, tuple[int, int, int], int]]:
    """
    Compatibility helper retained for tests/debug tooling.
    Production drawing uses true text measurement and centred placement.
    """
    status_color = (235, 90, 70) if error else (215, 225, 230)

    return [
        ((0, STARTUP_TITLE_CENTER_Y), STARTUP_TITLE, (255, 200, 40), STARTUP_TITLE_SIZE),
        ((0, STARTUP_STATUS_CENTER_Y), status_text, status_color, STARTUP_STATUS_SIZE),
    ]


def draw_startup_frame(
    status_text: str = STARTUP_INITIALIZING,
    *,
    error: bool = False,
    font_path: str | None = None,
    font_size: int = 24,
):
    """Draw a true centred 1280x1024 dark startup screen."""

    del font_size

    canvas = np.full(
        (STARTUP_HEIGHT, STARTUP_WIDTH, 3),
        (14, 18, 24),
        dtype=np.uint8,
    )

    image = Image.fromarray(
        cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    )

    draw = ImageDraw.Draw(image)

    resolved_font = _resolve_font(font_path)

    title_font = ImageFont.truetype(
        resolved_font,
        STARTUP_TITLE_SIZE,
    )

    status_font = ImageFont.truetype(
        resolved_font,
        STARTUP_STATUS_SIZE,
    )

    _draw_centered_text(
        draw,
        STARTUP_TITLE,
        title_font,
        STARTUP_TITLE_CENTER_Y,
        (255, 200, 40),
    )

    status_color = (
        (235, 100, 90)
        if error
        else (230, 225, 215)
    )

    _draw_centered_text(
        draw,
        status_text,
        status_font,
        STARTUP_STATUS_CENTER_Y,
        status_color,
    )

    return cv2.cvtColor(
        np.asarray(image),
        cv2.COLOR_RGB2BGR,
    )


def startup_failure_message(error: BaseException) -> str:
    """Convert fatal startup exceptions to a concise operator-facing message."""

    detail = str(error).casefold()

    if "picamera" in detail or "camera" in detail:
        return "摄像头初始化失败"

    if "model" in detail or "yolo" in detail:
        return "视觉模型加载失败"

    return "系统启动失败"


class StartupScreen:
    """Draw only before live processing starts."""

    def __init__(
        self,
        window_name: str | None,
        display: Mapping[str, object] | None = None,
    ) -> None:

        self.window_name = window_name

        options = display or {}

        font = options.get("font_path")
        self.font_path = str(font) if font else None

    @property
    def enabled(self) -> bool:
        return self.window_name is not None

    def show(
        self,
        status_text: str = STARTUP_INITIALIZING,
        *,
        error: bool = False,
    ) -> None:

        if not self.enabled:
            return

        frame = draw_startup_frame(
            status_text,
            error=error,
            font_path=self.font_path,
        )

        cv2.imshow(self.window_name, frame)

        # 让 xcb / XWayland 真正处理窗口映射和刷新。
        cv2.waitKey(1)

    def wait_for_exit(self) -> None:
        """Keep a fatal screen visible until local exit or Ctrl+C."""

        if not self.enabled:
            return

        while True:
            key = cv2.waitKey(100) & 0xFF

            if key in (27, ord("q")):
                return
