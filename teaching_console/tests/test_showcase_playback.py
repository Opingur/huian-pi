import unittest

from teaching_console.pages.showcase_page import format_showcase_time


class ShowcasePlaybackTests(unittest.TestCase):
    def test_formats_compact_video_time(self):
        self.assertEqual(format_showcase_time(0.0), "0:00")
        self.assertEqual(format_showcase_time(65.9), "1:05")
        self.assertEqual(format_showcase_time(None), "—")


if __name__ == "__main__":
    unittest.main()