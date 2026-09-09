import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "teaching_console" / "pages" / "showcase_page.py"


class ShowcasePageLayoutTests(unittest.TestCase):
    def test_fixed_cases_live_in_the_right_showcase_sidebar_not_a_toolbar_dropdown(self):
        source = PAGE.read_text(encoding="utf-8")
        self.assertIn("self._build_media_navigation(self.content)", source)
        self.assertIn('text="展示视频"', source)
        self.assertIn('text="可用素材"', source)
        self.assertIn('"演示选中视频"', source)
        self.assertNotIn("self.case_picker", source)
        self.assertNotIn("ttk.Combobox(", source)
        self.assertIn("ttk.Scale(", source)
        self.assertIn("self.toolbar.pack(side=\"bottom\"", source)
        self.assertNotIn("self.toolbar.place(", source)
        self.assertNotIn('self.image.bind("<Motion>", self._reveal_toolbar)', source)
        self.assertNotIn("self.after(4500, self._hide_toolbar)", source)
        self.assertIn('self.image.bind("<Button-1>", self._toggle_play_shortcut)', source)
        self.assertIn("UI_POLL_MS = 16", source)
        self.assertIn("self.after(self.UI_POLL_MS, self._drain_events)", source)
        self.assertIn("latest_frame", source)
        self.assertNotIn("Ctrl+O 选择本地视频", source)
        for title in ("案例② · 跟踪行人", "案例④ · 人流趋势"):
            self.assertIn(title, source)
        for title in ("案例① · 人数变多", "案例③ · 人数变少"):
            self.assertNotIn(title, source)


if __name__ == "__main__":
    unittest.main()
