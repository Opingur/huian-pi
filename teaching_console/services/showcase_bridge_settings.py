"""Local-only credentials for the Windows-to-Pi presentation bridge."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from teaching_console.runtime_paths import ensure_writable_data_root


@dataclass(frozen=True)
class ShowcaseBridgeSettings:
    bridge_key: str = ""


class ShowcaseBridgeSettingsStore:
    """Keep the existing Pi bridge key outside source control and outside the UI."""

    def __init__(self, project_root: Path) -> None:
        self.path = ensure_writable_data_root(project_root) / "showcase_bridge.json"

    def load(self) -> ShowcaseBridgeSettings:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return ShowcaseBridgeSettings()
        if not isinstance(payload, dict):
            return ShowcaseBridgeSettings()
        return ShowcaseBridgeSettings(str(payload.get("bridge_key", "")).strip())

    def save(self, settings: ShowcaseBridgeSettings) -> None:
        self.path.write_text(
            json.dumps({"bridge_key": settings.bridge_key.strip()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
