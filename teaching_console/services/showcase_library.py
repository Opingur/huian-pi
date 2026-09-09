"""Local video-library and processed-history support for the showcase page.

The two lists intentionally have different roots:

* ``展示端正式视频素材`` is the teacher-maintained library of source videos.
* ``output/demo_candidates`` contains already processed Dashboard exports.

History entries retain the *source* video path.  Selecting one therefore runs
the live presentation pipeline on the original video instead of feeding an
already annotated Dashboard video back into YOLO.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from teaching_console.runtime_paths import ensure_writable_data_root


VIDEO_SUFFIXES = frozenset({".mp4", ".avi", ".mov", ".mkv"})
HIDDEN_LIBRARY_FOLDERS = frozenset({"待人工确认", "待审核下载"})


@dataclass(frozen=True)
class ShowcaseVideoEntry:
    """One selectable original video, with a short user-facing label."""

    path: Path
    label: str
    source: str


def _is_video(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES


def _label(relative: Path) -> str:
    """Keep category context while preventing a long absolute path in the UI."""
    parent = " / ".join(relative.parts[:-1])
    return f"{parent} · {relative.stem}" if parent else relative.stem


def folder_entries(folder: Path) -> list[ShowcaseVideoEntry]:
    """List original videos from a presenter-selected folder without copying them."""
    root = Path(folder)
    if not root.is_dir():
        return []
    entries = [
        ShowcaseVideoEntry(path=path, label=_label(path.relative_to(root)), source="folder")
        for path in root.rglob("*") if _is_video(path)
    ]
    return sorted(entries, key=lambda item: item.label.casefold())


def library_entries(project_root: Path) -> list[ShowcaseVideoEntry]:
    """Return teacher-maintained showcase sources, excluding review downloads."""
    root = Path(project_root) / "展示端正式视频素材"
    if not root.is_dir():
        return []
    entries: list[ShowcaseVideoEntry] = []
    for path in root.rglob("*"):
        if not _is_video(path):
            continue
        relative = path.relative_to(root)
        if any(part in HIDDEN_LIBRARY_FOLDERS for part in relative.parts):
            continue
        entries.append(ShowcaseVideoEntry(path=path, label=_label(relative), source="library"))
    return sorted(entries, key=lambda item: item.label.casefold())


def _history_source(project_root: Path, summary_path: Path) -> ShowcaseVideoEntry | None:
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    raw_source = str(data.get("source_video") or "").strip()
    if not raw_source:
        return None
    source = Path(raw_source)
    if not source.is_absolute():
        source = Path(project_root) / source
    if not _is_video(source):
        return None
    title = str(data.get("title") or data.get("case_id") or source.stem).strip()
    generated_at = str(data.get("generated_at") or "").replace("T", " ").replace("+00:00", "")
    label = f"{title} · {generated_at[:16]}" if generated_at else title
    return ShowcaseVideoEntry(path=source, label=label, source="history")


def history_entries(project_root: Path) -> list[ShowcaseVideoEntry]:
    """Read successful offline Dashboard exports that still have their source."""
    root = ensure_writable_data_root(project_root) / "output" / "demo_candidates"
    if not root.is_dir():
        return []
    entries = [
        entry
        for summary in root.glob("*/summary.json")
        if (entry := _history_source(project_root, summary)) is not None
    ]
    return sorted(entries, key=lambda item: item.label, reverse=True)
