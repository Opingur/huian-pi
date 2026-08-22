"""Writable locations for teaching-console data in source and PyInstaller modes."""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def writable_data_root(project_root: Path) -> Path:
    """Return a stable user-data directory, never PyInstaller's temporary bundle path.

    In source mode the repository remains the natural working directory.  In an
    onedir build, generated datasets and imported models live beside the EXE so
    copying the whole onedir directory keeps the teaching artifacts together.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent / "huian_teaching_data"
    return Path(project_root).resolve()


def ensure_writable_data_root(project_root: Path) -> Path:
    root = writable_data_root(project_root)
    root.mkdir(parents=True, exist_ok=True)
    return root
