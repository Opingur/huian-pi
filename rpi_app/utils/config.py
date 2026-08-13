"""Raspberry Pi 视觉端配置加载与可移植路径解析。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parents[1]


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path is not None else APP_DIR / "config.json"
    with path.open("r", encoding="utf-8") as config_file:
        return json.load(config_file)


def resolve_app_path(configured_path: str) -> Path:
    """将配置中相对 rpi_app 的路径解析为绝对路径。"""
    return (APP_DIR / configured_path).resolve()
