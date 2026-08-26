from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
import sqlite3
from types import SimpleNamespace
import unittest

from teaching_console.pages.model_optimization_page import ModelOptimizationPage
from teaching_console.services.model_optimization_vision_service import ModelOptimizationVisionService
from teaching_console.services.vision_teaching_service import VisionTeachingWorker, WorkerResult


class _Value:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class DifficultFrameProgressTests(unittest.TestCase):
    def test_opening_video_requests_first_raw_frame_for_preview(self) -> None:
        page = ModelOptimizationPage.__new__(ModelOptimizationPage)
        page.video_var = _Value()
        page.status_var = _Value()
        page.analysis_progress_var = _Value()
        sent: list[tuple[str, tuple[object, ...]]] = []
        page._send = lambda operation, *args: sent.append((operation, args))
        video = SimpleNamespace(path=Path("sample.mp4"), width=1920, height=1080, fps=25.0)

        page._handle("open_video", video)

        self.assertIs(page.video, video)
        self.assertEqual(sent, [("read_raw", (0,))])

    def test_analysis_reports_each_sample_without_loading_yolo(self) -> None:
        service = ModelOptimizationVisionService.__new__(ModelOptimizationVisionService)
        service.video = SimpleNamespace(total_frames=100)
        service.detect = lambda index: SimpleNamespace(
            seconds=index / 25.0,
            rows=(SimpleNamespace(confidence=0.45),),
        )
        progress: list[tuple[int, int]] = []

        rows = service.analyze_difficult_frames(
            maximum=5,
            progress_callback=lambda completed, total: progress.append((completed, total)),
        )

        self.assertGreaterEqual(len(rows), 5)
        self.assertEqual(progress[0][0], 1)
        self.assertEqual(progress[-1], (25, 25))

    def test_worker_forwards_analysis_progress_to_tk_queue(self) -> None:
        class _Service:
            def analyze_difficult_frames(self, _maximum, progress_callback=None):
                assert progress_callback is not None
                progress_callback(1, 3)
                progress_callback(3, 3)
                return ("done",)

            def close(self):
                return None

        worker = VisionTeachingWorker(_Service())
        self.addCleanup(worker.close)
        worker.submit(7, "analyze_difficult_frames", 5)
        results = []
        while len(results) < 3:
            try:
                results.append(worker.results.get(timeout=1.0))
            except Empty as error:
                self.fail(f"worker did not forward progress: {error}")

        self.assertEqual(
            [(result.operation, result.value) for result in results],
            [
                ("analyze_difficult_frames_progress", (1, 3)),
                ("analyze_difficult_frames_progress", (3, 3)),
                ("analyze_difficult_frames", ("done",)),
            ],
        )



    def test_page_keeps_analysis_busy_while_progress_arrives(self) -> None:
        page = ModelOptimizationPage.__new__(ModelOptimizationPage)
        page.closing = False
        page.token = 9
        page.busy = True
        page.analysis_sample_total = 0
        page.analysis_progress_var = _Value()
        page.status_var = _Value()
        page.worker = SimpleNamespace(results=Queue())
        page.after = lambda *_args: None
        page.worker.results.put(
            WorkerResult(9, "analyze_difficult_frames_progress", (4, 25))
        )

        page._drain()

        self.assertTrue(page.busy)
        self.assertEqual(page.analysis_sample_total, 25)
        self.assertIn("4 / 25", page.analysis_progress_var.value)

    def test_refreshing_an_empty_candidate_list_does_not_delete_without_items(self) -> None:
        class _Tree:
            def __init__(self) -> None:
                self.delete_calls = 0
            def get_children(self):
                return ()
            def delete(self, *items):
                self.delete_calls += 1
                if not items:
                    raise AssertionError("Treeview.delete must not be called with no items")

        page = ModelOptimizationPage.__new__(ModelOptimizationPage)
        page.frame_rows = []
        page.frame_tree = _Tree()

        page._refresh_frames()

        self.assertEqual(page.frame_tree.delete_calls, 0)

    def test_selected_frame_requests_ai_boxes_after_raw_frame_is_shown(self) -> None:
        class _Flag:
            def get(self) -> bool:
                return True

        page = ModelOptimizationPage.__new__(ModelOptimizationPage)
        page.current_frame = {"frame_index": 42}
        page.show_system_var = _Flag()
        page.analysis_progress_var = _Value()
        page._save_raw_frame = lambda: None
        page._redraw = lambda: None
        page._redraw_preview = lambda: None
        sent = []
        page._send = lambda operation, *args: sent.append((operation, args))

        page._show_raw(SimpleNamespace(frame_bgr=object()))

        self.assertEqual(sent, [("detect", (42,))])

    def test_saved_child_boxes_create_an_honest_instant_correction_message(self) -> None:
        page = ModelOptimizationPage.__new__(ModelOptimizationPage)
        page.current_frame = {"system_count": 5}
        page.boxes = [object()] * 7
        page.instant_feedback_var = _Value()

        page._update_instant_feedback()

        self.assertIn("AI 原来数 5 人", page.instant_feedback_var.value)
        self.assertIn("少数了 2 人", page.instant_feedback_var.value)
        self.assertIn("还不表示模型已经训练完成", page.instant_feedback_var.value)
    def test_instant_feedback_accepts_sqlite_row_after_saving_boxes(self) -> None:
        with sqlite3.connect(":memory:") as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("CREATE TABLE frame (system_count INTEGER)")
            connection.execute("INSERT INTO frame VALUES (5)")
            stored_frame = connection.execute("SELECT system_count FROM frame").fetchone()

            page = ModelOptimizationPage.__new__(ModelOptimizationPage)
            page.current_frame = stored_frame
            page.boxes = [object()] * 7
            page.instant_feedback_var = _Value()

            page._update_instant_feedback()

        self.assertIn("AI 原来数 5 人", page.instant_feedback_var.value)
        self.assertIn("少数了 2 人", page.instant_feedback_var.value)
    def test_existing_legacy_video_project_is_reused_in_child_lab(self) -> None:
        class _Split:
            def get(self) -> str:
                return "train"

        class _Tree:
            def selection_set(self, _item_id) -> None:
                pass

            def focus(self, _item_id) -> None:
                pass

        class _Store:
            def __init__(self) -> None:
                self.rows = []

            def list_detection_annotation_projects(self, _dataset_name):
                return [{"id": "legacy-val", "source_video": "same.mp4", "split_name": "val"}]

            def detection_frame_annotations(self, _project_id):
                return list(self.rows)

            def create_detection_frame_annotation(self, project_id, frame_index, time_seconds, *_args, **_kwargs):
                self.rows.append({"id": "frame-1", "project_id": project_id, "frame_index": frame_index,
                                  "time_seconds": time_seconds})

        page = ModelOptimizationPage.__new__(ModelOptimizationPage)
        page.video = SimpleNamespace(path=Path("same.mp4"), width=640, height=480)
        page.split_var = _Split()
        page.store = _Store()
        page.growth_project_ids = set()
        page.frame_tree = _Tree()
        page.status_var = _Value()
        page.analysis_progress_var = _Value()
        page.analysis_sample_total = 1
        page._refresh_frames = lambda: None
        page._update_progress = lambda: None
        page.select_frame = lambda: None
        candidate = SimpleNamespace(frame_index=12, time_seconds=0.5, system_count=3,
                                    average_confidence=0.6, minimum_confidence=0.4, reasons=("遮挡",))

        page._save_recommendations((candidate,))

        self.assertEqual(page.project_id, "legacy-val")
        self.assertEqual([row["frame_index"] for row in page.frame_rows], [12])
        self.assertIn("困难帧候选", page.status_var.value)
if __name__ == "__main__":
    unittest.main()
