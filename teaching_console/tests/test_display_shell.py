import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "teaching_console" / "app.py"


class DisplayShellTests(unittest.TestCase):
    def test_showcase_shell_has_no_experiment_switch_entry(self):
        source = APP.read_text(encoding="utf-8")

        self.assertNotIn('text="切换到实验"', source)
        self.assertNotIn("self.display_switch", source)


if __name__ == "__main__":
    unittest.main()