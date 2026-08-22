"""SQLite persistence for research evidence and model-optimization records.

The original count and prediction Ground Truth tables deliberately remain
unchanged. Detection annotation and fine-tuning records live in independent
tables so older research databases can be opened without data migration or
loss.
"""
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
                CREATE TABLE IF NOT EXISTS prediction_annotations (
                    id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL,
                    anchor_time_seconds REAL NOT NULL,
                    anchor_frame_index INTEGER NOT NULL,
                    current_system_count INTEGER NOT NULL,
                    prediction_slope REAL,
                    prediction_10 REAL,
                    prediction_20 REAL,
                    prediction_30 REAL,
                    gt_10 INTEGER,
                    gt_20 INTEGER,
                    gt_30 INTEGER,
                    error_10 REAL,
                    error_20 REAL,
                    error_30 REAL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS detection_annotation_projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_video TEXT NOT NULL,
                    split_name TEXT NOT NULL DEFAULT 'unassigned',
                    dataset_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS detection_frame_annotations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    source_video TEXT NOT NULL,
                    frame_index INTEGER NOT NULL,
                    video_time_seconds REAL NOT NULL,
                    image_path TEXT,
                    image_width INTEGER NOT NULL,
                    image_height INTEGER NOT NULL,
                    system_count INTEGER,
                    average_confidence REAL,
                    minimum_confidence REAL,
                    recommendation_reasons TEXT NOT NULL DEFAULT '',
                    kept INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, frame_index)
                );
                CREATE TABLE IF NOT EXISTS detection_person_boxes (
                    id TEXT PRIMARY KEY,
                    frame_annotation_id TEXT NOT NULL,
                    class_id INTEGER NOT NULL DEFAULT 0,
                    x1 REAL NOT NULL,
                    y1 REAL NOT NULL,
                    x2 REAL NOT NULL,
                    y2 REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_experiments (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    dataset_name TEXT NOT NULL,
                    base_model_path TEXT NOT NULL,
                    epochs INTEGER,
                    imgsz INTEGER,
                    training_package_path TEXT,
                    candidate_model_path TEXT,
                    result_metadata_path TEXT,
                    status TEXT NOT NULL DEFAULT 'draft',
                    candidate_state TEXT NOT NULL DEFAULT 'pending',
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_deployments (
                    id TEXT PRIMARY KEY,
                    model_experiment_id TEXT NOT NULL,
                    target_host TEXT NOT NULL,
                    remote_project_path TEXT NOT NULL,
                    previous_model_path TEXT,
                    deployed_model_path TEXT NOT NULL,
                    previous_config_value TEXT,
                    status TEXT NOT NULL DEFAULT 'planned',
                    rollback_status TEXT NOT NULL DEFAULT 'not_requested',
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    rolled_back_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_detection_frames_project
                    ON detection_frame_annotations(project_id, frame_index);
                CREATE INDEX IF NOT EXISTS idx_detection_boxes_frame
                    ON detection_person_boxes(frame_annotation_id);
                CREATE INDEX IF NOT EXISTS idx_model_experiments_dataset
                    ON model_experiments(dataset_name, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_model_deployments_experiment
                    ON model_deployments(model_experiment_id, created_at DESC);
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


    def create_prediction_annotation(self, experiment_id: str, anchor_time_seconds: float, anchor_frame_index: int, current_system_count: int, prediction_slope: float | None, prediction_10: float | None, prediction_20: float | None, prediction_30: float | None, note: str = "") -> str:
        annotation_id, created = uuid.uuid4().hex, _utc_now()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO prediction_annotations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, ?)",
                (annotation_id, experiment_id, anchor_time_seconds, anchor_frame_index, current_system_count, prediction_slope, prediction_10, prediction_20, prediction_30, note, created, created),
            )
        return annotation_id

    def prediction_annotations(self, experiment_id: str) -> list[sqlite3.Row]:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute("SELECT * FROM prediction_annotations WHERE experiment_id = ? ORDER BY anchor_time_seconds", (experiment_id,)).fetchall()

    def update_prediction_ground_truth(self, annotation_id: str, horizon_seconds: int, ground_truth_count: int) -> None:
        if horizon_seconds not in (10, 20, 30):
            raise ValueError("预测 horizon 仅支持 10、20、30 秒。")
        prediction_column, gt_column, error_column = (f"prediction_{horizon_seconds}", f"gt_{horizon_seconds}", f"error_{horizon_seconds}")
        with self._connection() as connection:
            row = connection.execute(f"SELECT {prediction_column} FROM prediction_annotations WHERE id = ?", (annotation_id,)).fetchone()
            if row is None:
                raise KeyError(f"未知预测标注：{annotation_id}")
            error = None if row[0] is None else abs(float(row[0]) - ground_truth_count)
            connection.execute(f"UPDATE prediction_annotations SET {gt_column} = ?, {error_column} = ?, updated_at = ? WHERE id = ?", (ground_truth_count, error, _utc_now(), annotation_id))

    # Detection Ground Truth -------------------------------------------------

    @staticmethod
    def _validate_detection_split(split_name: str) -> str:
        if split_name not in {"train", "val", "test", "unassigned"}:
            raise ValueError("Detection 数据集划分仅支持 train、val、test 或 unassigned。")
        return split_name

    def create_detection_annotation_project(
        self,
        name: str,
        source_video: str | Path,
        split_name: str = "unassigned",
        dataset_name: str = "",
        status: str = "draft",
        description: str = "",
    ) -> str:
        """Create one video-level Detection Ground Truth project.

        The split belongs to the complete source video, never to an individual
        frame. Dataset construction can therefore reject video-level leakage.
        """
        project_id, created = uuid.uuid4().hex, _utc_now()
        self._validate_detection_split(split_name)
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO detection_annotation_projects "
                "(id, name, source_video, split_name, dataset_name, status, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, name, str(source_video), split_name, dataset_name, status, description, created, created),
            )
        return project_id

    def list_detection_annotation_projects(self, dataset_name: str | None = None) -> list[sqlite3.Row]:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            if dataset_name is None:
                return connection.execute(
                    "SELECT * FROM detection_annotation_projects ORDER BY created_at DESC, rowid DESC"
                ).fetchall()
            return connection.execute(
                "SELECT * FROM detection_annotation_projects WHERE dataset_name = ? "
                "ORDER BY created_at DESC, rowid DESC",
                (dataset_name,),
            ).fetchall()

    def get_detection_annotation_project(self, project_id: str) -> sqlite3.Row | None:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                "SELECT * FROM detection_annotation_projects WHERE id = ?", (project_id,)
            ).fetchone()

    def update_detection_annotation_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        split_name: str | None = None,
        dataset_name: str | None = None,
        status: str | None = None,
        description: str | None = None,
    ) -> None:
        values: dict[str, object] = {}
        if name is not None:
            values["name"] = name
        if split_name is not None:
            values["split_name"] = self._validate_detection_split(split_name)
        if dataset_name is not None:
            values["dataset_name"] = dataset_name
        if status is not None:
            values["status"] = status
        if description is not None:
            values["description"] = description
        if not values:
            return
        values["updated_at"] = _utc_now()
        assignments = ", ".join(f"{column} = ?" for column in values)
        with self._connection() as connection:
            result = connection.execute(
                f"UPDATE detection_annotation_projects SET {assignments} WHERE id = ?",
                (*values.values(), project_id),
            )
            if result.rowcount == 0:
                raise KeyError(f"未知 Detection 标注项目：{project_id}")

    def create_detection_frame_annotation(
        self,
        project_id: str,
        frame_index: int,
        video_time_seconds: float,
        image_width: int,
        image_height: int,
        *,
        source_video: str | Path | None = None,
        image_path: str | Path | None = None,
        system_count: int | None = None,
        average_confidence: float | None = None,
        minimum_confidence: float | None = None,
        recommendation_reasons: str = "",
        kept: bool = True,
    ) -> str:
        """Persist a recommended or manually selected raw video frame."""
        if image_width <= 0 or image_height <= 0:
            raise ValueError("标注帧必须具有正的原始图像宽度和高度。")
        project = self.get_detection_annotation_project(project_id)
        if project is None:
            raise KeyError(f"未知 Detection 标注项目：{project_id}")
        frame_id, created = uuid.uuid4().hex, _utc_now()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO detection_frame_annotations "
                "(id, project_id, source_video, frame_index, video_time_seconds, image_path, image_width, image_height, "
                "system_count, average_confidence, minimum_confidence, recommendation_reasons, kept, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    frame_id,
                    project_id,
                    str(source_video) if source_video is not None else project["source_video"],
                    int(frame_index),
                    float(video_time_seconds),
                    None if image_path is None else str(image_path),
                    int(image_width),
                    int(image_height),
                    system_count,
                    average_confidence,
                    minimum_confidence,
                    recommendation_reasons,
                    int(bool(kept)),
                    created,
                    created,
                ),
            )
        return frame_id

    def update_detection_frame_annotation(
        self,
        frame_annotation_id: str,
        *,
        image_path: str | Path | None = None,
        system_count: int | None = None,
        average_confidence: float | None = None,
        minimum_confidence: float | None = None,
        recommendation_reasons: str | None = None,
        kept: bool | None = None,
    ) -> None:
        values: dict[str, object] = {}
        if image_path is not None:
            values["image_path"] = str(image_path)
        if system_count is not None:
            values["system_count"] = int(system_count)
        if average_confidence is not None:
            values["average_confidence"] = float(average_confidence)
        if minimum_confidence is not None:
            values["minimum_confidence"] = float(minimum_confidence)
        if recommendation_reasons is not None:
            values["recommendation_reasons"] = recommendation_reasons
        if kept is not None:
            values["kept"] = int(bool(kept))
        if not values:
            return
        values["updated_at"] = _utc_now()
        assignments = ", ".join(f"{column} = ?" for column in values)
        with self._connection() as connection:
            result = connection.execute(
                f"UPDATE detection_frame_annotations SET {assignments} WHERE id = ?",
                (*values.values(), frame_annotation_id),
            )
            if result.rowcount == 0:
                raise KeyError(f"未知 Detection 标注帧：{frame_annotation_id}")

    def detection_frame_annotations(self, project_id: str, include_skipped: bool = True) -> list[sqlite3.Row]:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            query = "SELECT * FROM detection_frame_annotations WHERE project_id = ?"
            if not include_skipped:
                query += " AND kept = 1"
            return connection.execute(query + " ORDER BY frame_index", (project_id,)).fetchall()

    def get_detection_frame_annotation(self, frame_annotation_id: str) -> sqlite3.Row | None:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                "SELECT * FROM detection_frame_annotations WHERE id = ?", (frame_annotation_id,)
            ).fetchone()

    @staticmethod
    def _validate_person_box(class_id: int, x1: float, y1: float, x2: float, y2: float) -> None:
        if int(class_id) != 0:
            raise ValueError("当前 Detection Ground Truth 仅支持 person 类别（class_id=0）。")
        if float(x2) <= float(x1) or float(y2) <= float(y1):
            raise ValueError("人体框必须满足 x2 > x1 且 y2 > y1。")

    def create_detection_person_box(
        self, frame_annotation_id: str, x1: float, y1: float, x2: float, y2: float, class_id: int = 0
    ) -> str:
        self._validate_person_box(class_id, x1, y1, x2, y2)
        if self.get_detection_frame_annotation(frame_annotation_id) is None:
            raise KeyError(f"未知 Detection 标注帧：{frame_annotation_id}")
        box_id, created = uuid.uuid4().hex, _utc_now()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO detection_person_boxes "
                "(id, frame_annotation_id, class_id, x1, y1, x2, y2, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (box_id, frame_annotation_id, 0, float(x1), float(y1), float(x2), float(y2), created, created),
            )
        return box_id

    def detection_person_boxes(self, frame_annotation_id: str) -> list[sqlite3.Row]:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                "SELECT * FROM detection_person_boxes WHERE frame_annotation_id = ? ORDER BY rowid",
                (frame_annotation_id,),
            ).fetchall()

    def update_detection_person_box(
        self, box_id: str, x1: float, y1: float, x2: float, y2: float, class_id: int = 0
    ) -> None:
        self._validate_person_box(class_id, x1, y1, x2, y2)
        with self._connection() as connection:
            result = connection.execute(
                "UPDATE detection_person_boxes SET class_id = 0, x1 = ?, y1 = ?, x2 = ?, y2 = ?, updated_at = ? "
                "WHERE id = ?",
                (float(x1), float(y1), float(x2), float(y2), _utc_now(), box_id),
            )
            if result.rowcount == 0:
                raise KeyError(f"未知人体框：{box_id}")

    def delete_detection_person_box(self, box_id: str) -> None:
        with self._connection() as connection:
            result = connection.execute("DELETE FROM detection_person_boxes WHERE id = ?", (box_id,))
            if result.rowcount == 0:
                raise KeyError(f"未知人体框：{box_id}")

    def replace_detection_person_boxes(self, frame_annotation_id: str, boxes: list[dict[str, float]]) -> None:
        """Atomically replace all raw-coordinate person boxes for one frame."""
        for box in boxes:
            self._validate_person_box(int(box.get("class_id", 0)), box["x1"], box["y1"], box["x2"], box["y2"])
        if self.get_detection_frame_annotation(frame_annotation_id) is None:
            raise KeyError(f"未知 Detection 标注帧：{frame_annotation_id}")
        created = _utc_now()
        with self._connection() as connection:
            connection.execute("DELETE FROM detection_person_boxes WHERE frame_annotation_id = ?", (frame_annotation_id,))
            connection.executemany(
                "INSERT INTO detection_person_boxes "
                "(id, frame_annotation_id, class_id, x1, y1, x2, y2, created_at, updated_at) "
                "VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?)",
                [
                    (uuid.uuid4().hex, frame_annotation_id, float(box["x1"]), float(box["y1"]), float(box["x2"]), float(box["y2"]), created, created)
                    for box in boxes
                ],
            )

    # Candidate model and deployment records --------------------------------

    def create_model_experiment(
        self,
        name: str,
        dataset_name: str,
        base_model_path: str | Path,
        *,
        epochs: int | None = None,
        imgsz: int | None = None,
        training_package_path: str | Path | None = None,
        note: str = "",
    ) -> str:
        experiment_id, created = uuid.uuid4().hex, _utc_now()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO model_experiments "
                "(id, name, dataset_name, base_model_path, epochs, imgsz, training_package_path, candidate_model_path, "
                "result_metadata_path, status, candidate_state, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'draft', 'pending', ?, ?, ?)",
                (
                    experiment_id,
                    name,
                    dataset_name,
                    str(base_model_path),
                    epochs,
                    imgsz,
                    None if training_package_path is None else str(training_package_path),
                    note,
                    created,
                    created,
                ),
            )
        return experiment_id

    def get_model_experiment(self, experiment_id: str) -> sqlite3.Row | None:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute("SELECT * FROM model_experiments WHERE id = ?", (experiment_id,)).fetchone()

    def list_model_experiments(self, dataset_name: str | None = None) -> list[sqlite3.Row]:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            if dataset_name is None:
                return connection.execute("SELECT * FROM model_experiments ORDER BY created_at DESC, rowid DESC").fetchall()
            return connection.execute(
                "SELECT * FROM model_experiments WHERE dataset_name = ? ORDER BY created_at DESC, rowid DESC",
                (dataset_name,),
            ).fetchall()

    def set_model_candidate(
        self,
        experiment_id: str,
        candidate_model_path: str | Path,
        *,
        result_metadata_path: str | Path | None = None,
        status: str = "candidate_imported",
    ) -> None:
        with self._connection() as connection:
            result = connection.execute(
                "UPDATE model_experiments SET candidate_model_path = ?, result_metadata_path = ?, status = ?, "
                "candidate_state = 'pending', updated_at = ? WHERE id = ?",
                (str(candidate_model_path), None if result_metadata_path is None else str(result_metadata_path), status, _utc_now(), experiment_id),
            )
            if result.rowcount == 0:
                raise KeyError(f"未知模型实验：{experiment_id}")

    def set_model_candidate_state(self, experiment_id: str, candidate_state: str) -> None:
        if candidate_state not in {"pending", "accepted", "rejected"}:
            raise ValueError("候选模型状态仅支持 pending、accepted 或 rejected。")
        with self._connection() as connection:
            result = connection.execute(
                "UPDATE model_experiments SET candidate_state = ?, updated_at = ? WHERE id = ?",
                (candidate_state, _utc_now(), experiment_id),
            )
            if result.rowcount == 0:
                raise KeyError(f"未知模型实验：{experiment_id}")

    def create_model_deployment(
        self,
        model_experiment_id: str,
        target_host: str,
        remote_project_path: str,
        deployed_model_path: str,
        *,
        previous_model_path: str | None = None,
        previous_config_value: str | None = None,
        status: str = "planned",
    ) -> str:
        if self.get_model_experiment(model_experiment_id) is None:
            raise KeyError(f"未知模型实验：{model_experiment_id}")
        deployment_id, created = uuid.uuid4().hex, _utc_now()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO model_deployments "
                "(id, model_experiment_id, target_host, remote_project_path, previous_model_path, deployed_model_path, "
                "previous_config_value, status, rollback_status, error_message, created_at, updated_at, rolled_back_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'not_requested', '', ?, ?, NULL)",
                (
                    deployment_id,
                    model_experiment_id,
                    target_host,
                    remote_project_path,
                    previous_model_path,
                    deployed_model_path,
                    previous_config_value,
                    status,
                    created,
                    created,
                ),
            )
        return deployment_id

    def update_model_deployment(
        self, deployment_id: str, *, status: str | None = None, error_message: str | None = None
    ) -> None:
        values: dict[str, object] = {}
        if status is not None:
            values["status"] = status
        if error_message is not None:
            values["error_message"] = error_message
        if not values:
            return
        values["updated_at"] = _utc_now()
        assignments = ", ".join(f"{column} = ?" for column in values)
        with self._connection() as connection:
            result = connection.execute(
                f"UPDATE model_deployments SET {assignments} WHERE id = ?", (*values.values(), deployment_id)
            )
            if result.rowcount == 0:
                raise KeyError(f"未知部署记录：{deployment_id}")

    def mark_model_deployment_rolled_back(self, deployment_id: str) -> None:
        rolled_back_at = _utc_now()
        with self._connection() as connection:
            result = connection.execute(
                "UPDATE model_deployments SET status = 'rolled_back', rollback_status = 'completed', "
                "updated_at = ?, rolled_back_at = ? WHERE id = ?",
                (rolled_back_at, rolled_back_at, deployment_id),
            )
            if result.rowcount == 0:
                raise KeyError(f"未知部署记录：{deployment_id}")

    def model_deployments(self, model_experiment_id: str) -> list[sqlite3.Row]:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                "SELECT * FROM model_deployments WHERE model_experiment_id = ? ORDER BY created_at DESC, rowid DESC",
                (model_experiment_id,),
            ).fetchall()
    def validate_detection_dataset_splits(self, dataset_name: str) -> dict[str, str]:
        """Return the video-to-split map or reject video-level data leakage.

        A source video may have several annotation projects, but every project
        for that source within a dataset must carry the same non-empty split.
        """
        projects = self.list_detection_annotation_projects(dataset_name)
        assignments: dict[str, str] = {}
        for project in projects:
            source_video, split_name = project["source_video"], project["split_name"]
            if split_name == "unassigned":
                raise ValueError(f"源视频尚未分配 train/val/test：{source_video}")
            previous = assignments.get(source_video)
            if previous is not None and previous != split_name:
                raise ValueError(
                    f"同一源视频不能同时属于多个数据集划分：{source_video}（{previous} / {split_name}）"
                )
            assignments[source_video] = split_name
        return assignments

    def accept_model_candidate(self, experiment_id: str) -> None:
        self.set_model_candidate_state(experiment_id, "accepted")

    def reject_model_candidate(self, experiment_id: str) -> None:
        self.set_model_candidate_state(experiment_id, "rejected")

    def get_model_deployment(self, deployment_id: str) -> sqlite3.Row | None:
        with self._connection() as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute("SELECT * FROM model_deployments WHERE id = ?", (deployment_id,)).fetchone()