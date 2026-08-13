import unittest

import numpy as np

from ui.chinese_display import _draw_text, _load_font, _load_latin_font, _load_symbol_font, _text_runs
from ui.flow_group_visualizer import draw_flow_legend


class DashboardFontFallbackTests(unittest.TestCase):
    required_text = "A\u6d41 B\u6d41 C\u6d41 | MQ-2 | ESP32 | FIRE | NORMAL | 0\u4eba | 0.67 | +10\u79d2 | +20\u79d2 | +30\u79d2 | 30.4\u2103"
    latin_text = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-+.:/%()"

    @staticmethod
    def _glyph_mask(font, character):
        return bytes(font.getmask(character))

    def _assert_text_has_no_missing_glyphs(self, text):
        primary = _load_font(None, 24)
        latin = _load_latin_font(24)
        symbol = _load_symbol_font(24)
        runs = _text_runs(text, primary, latin, symbol)
        self.assertGreater(len(runs), 0)
        for run, font in runs:
            missing_mask = self._glyph_mask(font, "\uffff")
            for character in run:
                if character.isspace():
                    continue
                self.assertNotIn(character, {"\u25a1", "\u25a2", "\ufffd"})
                self.assertNotEqual(
                    self._glyph_mask(font, character),
                    missing_mask,
                    f"missing glyph for {character!r}",
                )

    def test_dashboard_font_chain_covers_full_latin_ascii_and_common_symbols(self):
        self._assert_text_has_no_missing_glyphs(self.latin_text)
        self._assert_text_has_no_missing_glyphs(self.required_text)

    def test_flow_legend_a_b_c_uses_the_same_unified_font_chain(self):
        image = np.zeros((160, 300, 3), dtype=np.uint8)
        entries = []
        draw_flow_legend(image, {
            1: {"label": "0", "color": (255, 0, 0)},
            2: {"label": "1", "color": (0, 255, 0)},
            3: {"label": "2", "color": (0, 0, 255)},
        }, entries)
        labels = [entry[1] for entry in entries]
        self.assertEqual(labels, ["A\u6d41", "B\u6d41", "C\u6d41"])
        self._assert_text_has_no_missing_glyphs(" ".join(labels))
        rendered = _draw_text(image, entries, None, 24)
        self.assertGreater(int(np.count_nonzero(rendered)), 0)

    def test_required_mixed_text_renders_through_the_unified_helper(self):
        image = np.zeros((100, 1280, 3), dtype=np.uint8)
        rendered = _draw_text(image, [((10, 20), self.required_text, (255, 255, 255), 24)], None, 24)
        self.assertGreater(int(np.count_nonzero(rendered)), 0)


if __name__ == "__main__":
    unittest.main()
