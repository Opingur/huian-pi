"""Project-root discovery shared by the teaching console."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


@dataclass(frozen=True)
class ProjectCheck:
    root: Path
    is_valid: bool
    missing: tuple[str, ...]


_REQUIRED_PATHS = (
    "rpi_app/vision/tracker.py",
    "rpi_app/communication/esp32.py",
    "esp32_firmware/huian_esp32/huian_esp32.ino",
    "validation/scripts/validate.py",
)


def project_root() -> Path:
    """Return the Huian_YOLO directory containing this package."""
    if getattr(sys, "frozen", False):
        # The onedir release keeps project resources beside the executable.
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def check_project(root: Path | None = None) -> ProjectCheck:
    """Check the few source files that define the current teaching baseline."""
    candidate = (root or project_root()).resolve()
    missing = tuple(item for item in _REQUIRED_PATHS if not (candidate / item).is_file())
    return ProjectCheck(candidate, not missing, missing)
