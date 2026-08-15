"""SQLite persistence for count-only Ground Truth v0.1."""
from __future__ import annotations

import sqlite3
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git_commit(project_root: Path) -> str | None:
    """Return a commit when available; metadata collection must never block research."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (FileNotFoundError, OSError, subprocess.CalledProcessError):
        return None


class ResearchStore:
    """Owns no persistent SQLite connection, avoiding Windows file locks."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.database_path = self.project_root / "validation" / "research_data" / "huian_research.sqlite3"
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    video_path TEXT NOT NULL,
                    experiment_type TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    git_commit TEXT
                );
                CREATE TABLE IF NOT EXISTS count_annotations (
                    id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL,
                    sample_index INTEGER NOT NULL,
                    video_time_seconds REAL NOT NULL,
                    frame_index INTEGER NOT NULL,
                    system_count INTEGER,
                    ground_truth_count INTEGER,
                    absolute_error REAL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(experiment_id, sample_index)
                );
                """
            )

    def create_experiment(
        self, name: str, video_path: str | Path, experiment_type: str, description: str = ""
    ) -> str:
        experiment_id = uuid.uuid4().hex
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?, ?)",
                (experiment_id, name, str(video_path), experiment_type, description, _utc_now(), _git_commit(self.project_root)),
            )
        return experiment_id

    def list_experiments(self) -> list[sqlite3.Row]:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute("SELECT * FROM experiments ORDER BY created_at DESC, rowid DESC").fetchall()

    def get_experiment(self, experiment_id: str) -> sqlite3.Row | None:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()

    def create_count_annotation(
        self, experiment_id: str, sample_index: int, video_time_seconds: float, frame_index: int, system_count: int | None = None, note: str = ""
    ) -> str:
        annotation_id, created = uuid.uuid4().hex, _utc_now()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO count_annotations VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)",
                (annotation_id, experiment_id, sample_index, video_time_seconds, frame_index, system_count, note, created, created),
            )
        return annotation_id

    def update_system_count(self, annotation_id: str, system_count: int) -> None:
        with self._connection() as connection:
            row = connection.execute("SELECT ground_truth_count FROM count_annotations WHERE id = ?", (annotation_id,)).fetchone()
            if row is None:
                raise KeyError(f"未知标注任务：{annotation_id}")
            error = None if row[0] is None else abs(system_count - row[0])
            connection.execute("UPDATE count_annotations SET system_count = ?, absolute_error = ?, updated_at = ? WHERE id = ?", (system_count, error, _utc_now(), annotation_id))

    def update_ground_truth(self, experiment_id: str, sample_index: int, ground_truth_count: int, note: str = "") -> None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT system_count FROM count_annotations WHERE experiment_id = ? AND sample_index = ?",
                (experiment_id, sample_index),
            ).fetchone()
            if row is None:
                raise KeyError(f"未知标注任务：{experiment_id}/{sample_index}")
            connection.execute(
                "UPDATE count_annotations SET ground_truth_count = ?, absolute_error = ?, note = ?, updated_at = ? "
                "WHERE experiment_id = ? AND sample_index = ?",
                (ground_truth_count, None if row[0] is None else abs(row[0] - ground_truth_count), note, _utc_now(), experiment_id, sample_index),
            )

    def annotations(self, experiment_id: str) -> list[sqlite3.Row]:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                "SELECT * FROM count_annotations WHERE experiment_id = ? ORDER BY sample_index", (experiment_id,)
            ).fetchall()

    def progress(self, experiment_id: str) -> tuple[int, int]:
        with self._connection() as connection:
            completed, total = connection.execute(
                "SELECT COUNT(ground_truth_count), COUNT(*) FROM count_annotations WHERE experiment_id = ?", (experiment_id,)
            ).fetchone()
            return int(completed), int(total)
