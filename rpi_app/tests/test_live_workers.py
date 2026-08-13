import threading
import time
import unittest

import numpy as np

from vision.live_workers import LatestFrameWorker


class LatestFrameWorkerTests(unittest.TestCase):
    def test_busy_worker_overwrites_stale_pending_frame(self):
        first_started = threading.Event()
        release_first = threading.Event()
        third_completed = threading.Event()
        processed = []

        def process(frame, _timestamp):
            value = int(frame[0, 0, 0])
            processed.append(value)
            if value == 1:
                first_started.set()
                self.assertTrue(release_first.wait(1.0))
            if value == 3:
                third_completed.set()
            return value

        worker = LatestFrameWorker("test", process, 0.001)
        try:
            worker.submit(np.full((1, 1, 3), 1, dtype=np.uint8), 1.0)
            self.assertTrue(first_started.wait(1.0))
            worker.submit(np.full((1, 1, 3), 2, dtype=np.uint8), 2.0)
            worker.submit(np.full((1, 1, 3), 3, dtype=np.uint8), 3.0)
            release_first.set()
            self.assertTrue(third_completed.wait(1.0))
            self.assertEqual(processed, [1, 3])
            snapshot = worker.snapshot()
            self.assertEqual(snapshot.result, 3)
            self.assertEqual(snapshot.source_timestamp, 3.0)
        finally:
            release_first.set()
            worker.close()

    def test_worker_error_is_visible_and_worker_stops_cleanly(self):
        invoked = threading.Event()

        def fail(_frame, _timestamp):
            invoked.set()
            raise RuntimeError("expected test failure")

        worker = LatestFrameWorker("failure", fail, 0.001)
        try:
            worker.submit(np.zeros((1, 1, 3), dtype=np.uint8), 0.0)
            self.assertTrue(invoked.wait(1.0))
            deadline = time.monotonic() + 1.0
            snapshot = worker.snapshot()
            while snapshot.error is None and time.monotonic() < deadline:
                threading.Event().wait(0.01)
                snapshot = worker.snapshot()
            self.assertIn("RuntimeError: expected test failure", snapshot.error)
        finally:
            worker.close()


if __name__ == "__main__":
    unittest.main()