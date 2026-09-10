"""日志。

出问题的时候得有东西可看。写到 %USERPROFILE%\\.shiyi\\shiyi.log，
自动轮转，最多留 3 份，不会无限长。界面里「关于」页有一个按钮直接打开它。
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from .config import DATA_DIR

LOG_PATH = DATA_DIR / "shiyi.log"
_configured = False


def setup(level: int = logging.INFO, console: bool = True) -> logging.Logger:
    global _configured
    root = logging.getLogger("shiyi")
    if _configured:
        return root

    root.setLevel(logging.DEBUG)
    root.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)-14s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass                                    # 写不了日志也不该拦住程序

    if console and sys.stdout is not None:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(level)
        ch.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(ch)

    _configured = True
    _install_excepthook(root)
    return root


def _install_excepthook(logger: logging.Logger) -> None:
    """没人接住的异常也要留下痕迹，不然窗口一闪就没了什么都查不到。"""
    prev = sys.excepthook

    def hook(exc_type, exc, tb):
        if not issubclass(exc_type, KeyboardInterrupt):
            logger.critical("未捕获的异常", exc_info=(exc_type, exc, tb))
        prev(exc_type, exc, tb)

    sys.excepthook = hook


def tail(lines: int = 200) -> str:
    """读日志末尾，给「关于」页显示。"""
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as fh:
            return "".join(fh.readlines()[-lines:])
    except OSError:
        return "（还没有日志）"
