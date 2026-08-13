"""配置加载。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_config(config_path: str | Path = "config.json") -> dict[str, Any]:
    with Path(config_path).open("r", encoding="utf-8") as config_file:
        return json.load(config_file)
