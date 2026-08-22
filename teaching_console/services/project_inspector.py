"""Compatibility API for the verified teaching Source Map."""
from teaching_console.services.source_map_catalog import (
    SourceEntry, all_entries, engineering_entries, entry_exists,
    search_entries, source_entries, teaching_entries,
)

__all__ = [
    "SourceEntry", "all_entries", "engineering_entries", "entry_exists",
    "search_entries", "source_entries", "teaching_entries",
]
