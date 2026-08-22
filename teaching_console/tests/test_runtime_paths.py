from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from teaching_console.runtime_paths import ensure_writable_data_root, writable_data_root


class RuntimePathsTests(unittest.TestCase):
    def test_source_mode_uses_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("teaching_console.runtime_paths.is_frozen", return_value=False):
            root = Path(directory)
            self.assertEqual(root.resolve(), writable_data_root(root))

    def test_frozen_mode_uses_directory_beside_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("teaching_console.runtime_paths.is_frozen", return_value=True), patch(
            "teaching_console.runtime_paths.sys.executable", str(Path(directory) / "console.exe")
        ):
            output = ensure_writable_data_root(Path("ignored"))
            self.assertEqual(Path(directory) / "huian_teaching_data", output)
            self.assertTrue(output.is_dir())


if __name__ == "__main__":
    unittest.main()
