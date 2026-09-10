"""拾遗 Shiyi —— 本地作品档案馆 / a local archive for everything you've made."""
from __future__ import annotations

import sys
from pathlib import Path

__version__ = "1.0.0"
APP_NAME = "拾遗"
APP_NAME_EN = "Shiyi"


def resource_dir() -> Path:
    """静态资源的真实位置。

    PyInstaller 打包后，文件被解到 sys._MEIPASS 下，__file__ 指向的地方
    没有 web/ 目录。这个函数把两种情况抹平。
    """
    base = getattr(sys, "_MEIPASS", None)
    return (Path(base) / "shiyi") if base else Path(__file__).resolve().parent


def web_dir() -> Path:
    return resource_dir() / "web"
