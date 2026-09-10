"""应用外壳：单实例、后台服务、定时扫描、托盘、窗口。

这一层把「一个能跑的脚本」变成「一个软件」：
  · 再点一次图标 -> 唤起已经开着的那个，而不是又起一份
  · 关掉窗口 -> 收进托盘继续待命，不是退出
  · 每隔一段时间自己做增量扫描，你不用记得点「重新扫描」
  · 崩了有日志可查
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

from . import __version__, scan, store, web_dir
from .config import Config, DATA_DIR
from .logsetup import setup as setup_logging

RUNTIME_PATH = DATA_DIR / "runtime.json"
log = logging.getLogger("shiyi.app")


# ----------------------------------------------------------------- 单实例
class SingleInstance:
    """Windows 上用具名互斥体，其它平台退回锁文件。

    拿不到锁说明已经有一份在跑：读它写下的 runtime.json，把窗口唤起来，
    然后安静退出。这是双击图标应有的反应。
    """

    MUTEX_NAME = "Global\\ShiyiSingleInstance_v1"

    def __init__(self, name: str | None = None) -> None:
        # 名字可以覆盖，这样测试不会撞上真在跑的那一份
        self.name = name or self.MUTEX_NAME
        self._handle = None
        self._lock_file = None
        self.already_running = False

    def acquire(self) -> bool:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._handle = kernel32.CreateMutexW(None, False, self.name)
            self.already_running = ctypes.get_last_error() == 183   # ALREADY_EXISTS
            return not self.already_running
        lock = DATA_DIR / ("%s.lock" % self.name.split("\\")[-1])
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self._lock_file = open(lock, "w")
            import fcntl
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except Exception:
            self.already_running = True
            return False

    def release(self) -> None:
        if self._handle:
            import ctypes
            ctypes.WinDLL("kernel32").CloseHandle(self._handle)
            self._handle = None
        if self._lock_file:
            try:
                self._lock_file.close()
            except OSError:
                pass


def read_runtime() -> dict:
    try:
        return json.loads(RUNTIME_PATH.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def write_runtime(port: int, token: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_PATH.write_text(json.dumps(
        {"port": port, "token": token, "pid": os.getpid(),
         "version": __version__, "started": time.time()},
        ensure_ascii=False, indent=2), "utf-8")


def clear_runtime() -> None:
    try:
        RUNTIME_PATH.unlink()
    except OSError:
        pass


# ----------------------------------------------------------------- 自动扫描
class AutoScanner:
    """按间隔跑增量扫描。15 万文件的增量大约 9 秒，放后台不打扰人。"""

    def __init__(self, cfg_getter, on_done=None):
        self._cfg = cfg_getter
        self._on_done = on_done
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.progress = scan.Progress()
        self.last_run = 0.0
        self.last_message = ""
        self.running = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="shiyi-autoscan")
        self._thread.start()

    def trigger(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _loop(self) -> None:
        cfg = self._cfg()
        if cfg.scan_on_start:
            self._run_once()
        while not self._stop.is_set():
            cfg = self._cfg()
            minutes = cfg.auto_scan_minutes
            timeout = minutes * 60 if minutes > 0 else 3600
            woke = self._wake.wait(timeout)
            self._wake.clear()
            if self._stop.is_set():
                break
            if woke or minutes > 0:
                self._run_once()

    def _run_once(self) -> None:
        if self.running:
            return
        self.running = True
        con = None
        try:
            con = store.connect()
            p = self.progress
            t0 = time.time()
            scan.scan(con, self._cfg(), p)
            self.last_run = time.time()
            self.last_message = p.message
            log.info("自动扫描完成：%s（%.1fs）", p.message, time.time() - t0)
            if self._on_done:
                self._on_done(p)
        except Exception:
            log.exception("自动扫描出错")
        finally:
            if con is not None:
                con.close()
            self.running = False


# ----------------------------------------------------------------- 主程序
class Application:
    def __init__(self, *, tray: bool = True, open_window: bool | None = None,
                 port: int | None = None):
        self.cfg = Config.load()
        self.use_tray = tray
        self.port = port or self.cfg.port
        self.open_window_wanted = (self.cfg.open_window_on_start
                                   if open_window is None else open_window)
        self.instance = SingleInstance()
        self.httpd = None
        self.window = None
        self.tray = None
        self.scanner = None
        self._shutting_down = False

    # ------------------------------------------------------------- 启动
    def run(self) -> int:
        setup_logging(console=not self.use_tray)
        log.info("拾遗 %s 启动（tray=%s）", __version__, self.use_tray)

        if not self.instance.acquire():
            return self._greet_existing()

        from . import server
        server.APP = self
        self.httpd, self.port = server.bind(self.port)
        write_runtime(self.port, server.TOKEN)
        threading.Thread(target=self.httpd.serve_forever, daemon=True,
                         name="shiyi-http").start()
        log.info("服务已监听 127.0.0.1:%d", self.port)

        self.scanner = AutoScanner(lambda: Config.load(), self._on_scan_done)
        self.scanner.start()

        if self.open_window_wanted:
            self.show_window()

        if self.use_tray and sys.platform == "win32":
            return self._run_tray()
        return self._run_headless()

    def _greet_existing(self) -> int:
        rt = read_runtime()
        port = rt.get("port")
        if port:
            log.info("已经有一份在跑（pid=%s），把窗口唤起来", rt.get("pid"))
            self._open_url("http://127.0.0.1:%d/" % port)
        else:
            log.warning("检测到已在运行，但读不到 runtime.json")
        return 0

    # ------------------------------------------------------------- 界面
    def url(self) -> str:
        return "http://127.0.0.1:%d/" % self.port

    def show_window(self) -> None:
        from .window import AppWindow
        if self.window is None:
            self.window = AppWindow(DATA_DIR / "window",
                                    self.cfg.window_width, self.cfg.window_height)
        self.window.open(self.url())

    def _open_url(self, url: str) -> None:
        from .window import AppWindow
        AppWindow(DATA_DIR / "window").open(url)

    # ------------------------------------------------------------- 托盘
    def _run_tray(self) -> int:
        from .tray import TrayIcon, MenuItem, SEPARATOR

        icon = web_dir() / "icon.ico"

        def menu():
            busy = self.scanner.running
            items = [
                MenuItem("打开拾遗", self.show_window, default=True),
                SEPARATOR,
                MenuItem("扫描中…" if busy else "立即扫描",
                         self.scanner.trigger, enabled=not busy),
                MenuItem(self._scan_summary(), None, enabled=False),
                SEPARATOR,
                MenuItem("打开索引目录", self._open_data_dir),
                MenuItem("查看日志", self._open_log),
                SEPARATOR,
                MenuItem("退出", self.shutdown),
            ]
            return items

        self.tray = TrayIcon("拾遗 %s" % __version__, icon, menu,
                             on_activate=self.show_window)
        try:
            self.tray.show()
        except Exception:
            log.exception("托盘起不来，退回无托盘模式")
            return self._run_headless()

        try:
            self.tray.run()
        except KeyboardInterrupt:
            pass
        finally:
            self._cleanup()
        return 0

    def _run_headless(self) -> int:
        print("拾遗已启动  ->  " + self.url())
        print("（只监听本机；Ctrl+C 停止）")
        try:
            while not self._shutting_down:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print()
        finally:
            self._cleanup()
        return 0

    def _scan_summary(self) -> str:
        if self.scanner.last_message:
            when = time.strftime("%H:%M", time.localtime(self.scanner.last_run))
            return "上次扫描 %s · %s" % (when, self.scanner.last_message)
        return "还没有扫描过"

    def _on_scan_done(self, p) -> None:
        if self.tray:
            self.tray.set_tooltip("拾遗 · %s" % p.message)
            if p.added or p.removed:
                self.tray.notify("拾遗", "索引已更新：" + p.message)

    def _open_data_dir(self) -> None:
        self._reveal(str(DATA_DIR))

    def _open_log(self) -> None:
        from .logsetup import LOG_PATH
        self._reveal(str(LOG_PATH), select=True)

    @staticmethod
    def _reveal(path: str, select: bool = False) -> None:
        import subprocess
        try:
            if select:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                os.startfile(path)          # noqa: S606  用户自己点的
        except Exception:
            log.exception("打不开 %s", path)

    # ------------------------------------------------------------- 退出
    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        log.info("正在退出")
        if self.tray:
            self.tray.stop()

    def _cleanup(self) -> None:
        if self.scanner:
            self.scanner.stop()
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
        if self.window:
            self.window.close()
        clear_runtime()
        self.instance.release()
        log.info("已退出")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    tray = "--no-tray" not in argv
    no_window = "--no-window" in argv
    port = None
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            try:
                port = int(argv[i + 1])
            except ValueError:
                pass
    app = Application(tray=tray, open_window=not no_window, port=port)
    return app.run()
