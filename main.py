"""兼容入口：启动已归档到 pc_prototype 的电脑端原型。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PC_PROTOTYPE_DIR = Path(__file__).resolve().parent / "pc_prototype"
sys.path.insert(0, str(PC_PROTOTYPE_DIR))
_spec = importlib.util.spec_from_file_location("huian_pc_main", PC_PROTOTYPE_DIR / "main.py")
if _spec is None or _spec.loader is None:
    raise RuntimeError("无法加载 pc_prototype/main.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


if __name__ == "__main__":
    _module.main()
