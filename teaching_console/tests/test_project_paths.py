from __future__ import annotations

import unittest

from teaching_console.project_paths import check_project, project_root


class ProjectPathTests(unittest.TestCase):
    def test_current_repository_is_detected(self) -> None:
        result = check_project(project_root())
        self.assertTrue(result.is_valid, result.missing)


if __name__ == "__main__":
    unittest.main()
