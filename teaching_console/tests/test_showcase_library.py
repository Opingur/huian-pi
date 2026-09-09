import json
import tempfile
import unittest
from pathlib import Path

from teaching_console.services.showcase_library import folder_entries, history_entries, library_entries


class ShowcaseLibraryTests(unittest.TestCase):
    def test_library_lists_sources_and_hides_review_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = root / "展示端正式视频素材"
            approved = library / "01_人流趋势" / "人流.mp4"
            review = library / "待人工确认" / "候选.mp4"
            approved.parent.mkdir(parents=True); review.parent.mkdir(parents=True)
            approved.write_bytes(b"video"); review.write_bytes(b"video")

            entries = library_entries(root)

        self.assertEqual([(entry.path.name, entry.source) for entry in entries], [("人流.mp4", "library")])
        self.assertIn("01_人流趋势", entries[0].label)

    def test_selected_folder_lists_all_videos_without_copying(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "外部视频"
            nested = folder / "分组"
            nested.mkdir(parents=True)
            (folder / "走廊.mp4").write_bytes(b"video")
            (nested / "人流.mov").write_bytes(b"video")
            (folder / "说明.txt").write_text("not a video", encoding="utf-8")

            entries = folder_entries(folder)

        self.assertEqual([entry.path.name for entry in entries], ["人流.mov", "走廊.mp4"])
        self.assertTrue(all(entry.source == "folder" for entry in entries))

    def test_history_uses_original_source_not_dashboard_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "展示端正式视频素材" / "01_人流趋势" / "人流.mp4"
            source.parent.mkdir(parents=True); source.write_bytes(b"video")
            export = root / "output" / "demo_candidates" / "case_a"
            export.mkdir(parents=True)
            (export / "dashboard.mp4").write_bytes(b"dashboard")
            (export / "summary.json").write_text(json.dumps({
                "case_id": "case_a", "title": "人流趋势演示",
                "source_video": str(source.relative_to(root)),
                "generated_at": "2026-08-26T08:00:00+00:00",
            }), encoding="utf-8")

            entries = history_entries(root)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].path, source)
        self.assertEqual(entries[0].source, "history")
        self.assertIn("人流趋势演示", entries[0].label)

    def test_missing_or_invalid_history_source_is_not_selectable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export = root / "output" / "demo_candidates" / "missing"
            export.mkdir(parents=True)
            (export / "summary.json").write_text('{"source_video": "gone.mp4"}', encoding="utf-8")

            self.assertEqual(history_entries(root), [])


if __name__ == "__main__":
    unittest.main()
