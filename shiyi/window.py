"""应用窗口。

用 Edge / Chrome 的 --app 模式开一个没有地址栏、没有标签页的窗口，
看起来就是个独立软件。用独立的 user-data-dir，跟你平时的浏览器完全隔开：
不共享 Cookie、不出现在浏览历史里、关掉也不影响你原来开的网页。

找不到 Edge / Chrome 就退回默认浏览器——功能一样，只是多一圈浏览器外壳。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("shiyi.window")

# 找浏览器的顺序：Edge 在 Windows 上一定有，优先
_CANDIDATES = (
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
)


def find_browser() -> str | None:
    if sys.platform != "win32":
        return shutil.which("google-chrome") or shutil.which("chromium")
    for pat in _CANDIDATES:
        p = os.path.expandvars(pat)
        if "%" not in p and Path(p).is_file():
            return p
    return shutil.which("msedge") or shutil.which("chrome")


class AppWindow:
    """管一个应用窗口进程。同一时间只开一个。"""

    def __init__(self, profile_dir: Path, width: int = 1180, height: int = 780):
        self.profile_dir = Path(profile_dir)
        self.width = width
        self.height = height
        self._proc: subprocess.Popen | None = None

    def is_open(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def open(self, url: str) -> bool:
        """打开窗口；已经开着就什么都不做。返回是否用上了应用窗口模式。"""
        if self.is_open():
            return True
        exe = find_browser()
        if not exe:
            log.info("没找到 Edge / Chrome，退回默认浏览器")
            return self._fallback(url)

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        args = [
            exe,
            "--app=" + url,
            "--user-data-dir=" + str(self.profile_dir),
            "--window-size=%d,%d" % (self.width, self.height),
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-features=Translate,OptimizationHints",
        ]
        try:
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW
            self._proc = subprocess.Popen(
                args, close_fds=True, creationflags=flags,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log.info("应用窗口已打开：%s", Path(exe).name)
            return True
        except OSError:
            log.exception("启动应用窗口失败，退回默认浏览器")
            return self._fallback(url)

    def _fallback(self, url: str) -> bool:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            log.exception("连默认浏览器都打不开")
        return False

    def close(self) -> None:
        if not self.is_open():
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None
