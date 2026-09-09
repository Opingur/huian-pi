"""Remember source videos that have been played through the local showcase."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from teaching_console.runtime_paths import ensure_writable_data_root


_HISTORY_FILE = Path("output") / "showcase_history" / "processed_sources.json"
_VIDEO_SUFFIXES = frozenset({".mp4", ".avi", ".mov", ".mkv"})


@dataclass(frozen=True)
class RecentShowcaseVideo:
    path: Path
    label: str


def _is_video(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in _VIDEO_SUFFIXES


def record_recent_video(project_root: Path, video_path: Path) -> None:
    """Store a pointer to an original video after its first rendered frame."""
    root = ensure_writable_data_root(project_root)
    source = Path(video_path).resolve()
    if not _is_video(source):
        return
    target = root / _HISTORY_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else []
    except (OSError, ValueError, TypeError):
        data = []
    records = [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    try:
        source_text = str(source.relative_to(root))
    except ValueError:
        source_text = str(source)
    records = [item for item in records if str(item.get("source_video") or "") != source_text]
    records.insert(0, {
        "source_video": source_text,
        "title": source.stem,
        "played_at": datetime.now(timezone.utc).isoformat(),
    })
    target.write_text(json.dumps(records[:30], ensure_ascii=False, indent=2), encoding="utf-8")


def recent_videos(project_root: Path) -> list[RecentShowcaseVideo]:
    root = ensure_writable_data_root(project_root)
    target = root / _HISTORY_FILE
    try:
        data = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else []
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    result: list[RecentShowcaseVideo] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_path = Path(str(item.get("source_video") or ""))
        source = raw_path if raw_path.is_absolute() else root / raw_path
        if not _is_video(source):
            continue
        title = str(item.get("title") or source.stem).strip()
        played_at = str(item.get("played_at") or "").replace("T", " ").replace("+00:00", "")
        result.append(RecentShowcaseVideo(source, f"{title} · {played_at[:16]}" if played_at else title))
    return result


def history_folder(project_root: Path) -> Path:
    return ensure_writable_data_root(project_root) / _HISTORY_FILE.parent
