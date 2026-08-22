from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from teaching_console.services.source_opening import code_g_command, open_source_file, pyinstaller_source_notice


class _Result:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode


class SourceOpeningTests(unittest.TestCase):
    def test_builds_code_g_command_with_requested_line(self) -> None:
        path = Path(r"C:\workspace\rpi_app\vision\detector.py")
        self.assertEqual(code_g_command(path, 18), ["code", "-g", r"C:\workspace\rpi_app\vision\detector.py:18"])

    def test_uses_vscode_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.py"; path.touch()
            calls: list[list[str]] = []
            result = open_source_file(path, 7, command_runner=lambda args, **_kwargs: calls.append(args) or _Result())
        self.assertTrue(result.opened)
        self.assertEqual(result.method, "vscode")
        self.assertEqual(calls[0][-1], f"{path}:7")

    def test_falls_back_to_windows_default_when_code_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.py"; path.touch()
            opened: list[str] = []
            result = open_source_file(
                path,
                command_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("code")),
                startfile=opened.append,
                platform_name="nt",
            )
        self.assertTrue(result.opened)
        self.assertEqual(result.method, "windows-default")
        self.assertEqual(opened, [str(path)])

    def test_pyinstaller_notice_is_explicit(self) -> None:
        self.assertIsNone(pyinstaller_source_notice(False))
        self.assertIn("打包版", pyinstaller_source_notice(True) or "")
