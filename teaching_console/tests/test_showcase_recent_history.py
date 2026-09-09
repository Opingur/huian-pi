import tempfile
import unittest
from pathlib import Path

from teaching_console.services.showcase_recent_history import recent_videos, record_recent_video


class ShowcaseRecentHistoryTests(unittest.TestCase):
    def test_recorded_source_is_reusable_and_is_not_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "展示端正式视频素材" / "人流.mp4"
            video.parent.mkdir(parents=True); video.write_bytes(b"video")

            record_recent_video(root, video)
            entries = recent_videos(root)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].path, video.resolve())
            self.assertTrue((root / "output" / "showcase_history" / "processed_sources.json").is_file())
            self.assertFalse(any(path.name == "人流.mp4" for path in (root / "output").rglob("*.mp4")))

    def test_repeated_video_stays_one_history_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "case.mp4"; video.write_bytes(b"video")
            record_recent_video(root, video); record_recent_video(root, video)
            self.assertEqual(len(recent_videos(root)), 1)


if __name__ == "__main__":
    unittest.main()
