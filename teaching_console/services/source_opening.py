"""Safe, testable source-file opening helpers for the teaching console.

The GUI owns message boxes; this module only describes whether VS Code or the
Windows file association was used.  Keeping that distinction outside Tk makes
the classroom buttons easy to test without launching an editor.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


@dataclass(frozen=True)
class SourceOpenResult:
    """The outcome of one source-opening attempt."""

    opened: bool
    method: str
    path: Path
    message: str = ""


def pyinstaller_source_notice(frozen: bool | None = None) -> str | None:
    """Return the editor warning appropriate for a frozen PyInstaller build."""
    running_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not running_frozen:
        return None
    return (
        "当前为打包版。修改随包源码不会改变已经冻结的 EXE；"
        "要修改教学软件本身需回到项目源码环境重新构建。"
    )


def code_g_command(path: Path, line: int | None = None) -> list[str]:
    """Build the documented VS Code command without using a shell."""
    target_line = max(1, int(line or 1))
    return ["code", "-g", f"{path}:{target_line}"]


def open_source_file(
    path: str | Path,
    line: int | None = None,
    *,
    command_runner: Callable[..., object] = subprocess.run,
    startfile: Callable[[str], object] | None = None,
    platform_name: str | None = None,
) -> SourceOpenResult:
    """Open *path* in VS Code first, then use the Windows file association.

    ``code`` is intentionally launched with ``shell=False``.  A missing CLI,
    an OS launch error, or a non-zero result falls through to ``os.startfile``
    on Windows.  Other platforms report the VS Code failure rather than
    pretending that a Windows-only fallback worked.
    """
    source_path = Path(path)
    if not source_path.is_file():
        return SourceOpenResult(False, "none", source_path, "源码文件不存在。")

    try:
        result = command_runner(code_g_command(source_path, line), check=False)
        if getattr(result, "returncode", 0) == 0:
            return SourceOpenResult(True, "vscode", source_path)
    except (FileNotFoundError, OSError) as error:
        code_error = str(error)
    else:
        code_error = "VS Code 命令返回非零状态。"

    is_windows = (platform_name or os.name) == "nt"
    fallback = startfile if startfile is not None else getattr(os, "startfile", None)
    if is_windows and fallback is not None:
        try:
            fallback(str(source_path))
            return SourceOpenResult(True, "windows-default", source_path, code_error)
        except OSError as error:
            return SourceOpenResult(False, "none", source_path, f"VS Code 与默认程序均无法打开：{error}")
    return SourceOpenResult(False, "none", source_path, f"无法启动 VS Code：{code_error}")
