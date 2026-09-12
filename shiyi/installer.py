"""安装与卸载。

装到 %LOCALAPPDATA%\\Programs\\拾遗 —— 当前用户名下，不要管理员权限。
写一条 HKCU 的卸载记录，于是「设置 → 应用」里能看到它，也能从那里卸。

卸载由程序自己承担（拾遗.exe --uninstall）：省掉一个单独的卸载器，
也就不会出现「卸载器被杀毒软件删了，程序卸不掉」这种事。
正在运行的 exe 删不掉自己，所以最后一步交给一个脱离出去的 cmd 收尾。
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from . import __version__, winui as U
from .winui import (DT_CENTER, DT_PATH_ELLIPSIS, FAINT, INK, INK_2, INK_3,
                    LINE, LINE_2, MUTED, PAPER, SEAL, SEAL_HI, SEAL_SOFT,
                    SURFACE, SURFACE_2, SURFACE_3)

APP_ID = "Shiyi"
APP_TITLE = "拾遗"
DISPLAY_NAME = "拾遗 Recollect"
HOMEPAGE = "https://github.com/seansinclair427-sq/recollect"
UNINSTALL_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
                 "\\" + APP_ID)

VK_ESCAPE, VK_RETURN = 0x1B, 0x0D


# ================================================================= 逻辑
def default_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / APP_TITLE


def installed_dir() -> Path | None:
    """装过吗？装在哪？"""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            loc, _ = winreg.QueryValueEx(k, "InstallLocation")
        p = Path(loc)
        return p if p.is_dir() else None
    except OSError:
        return None


def installed_version() -> str:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return winreg.QueryValueEx(k, "DisplayVersion")[0]
    except OSError:
        return ""


def payload() -> Path | None:
    """打包进来的程序本体。冻结时在 _MEIPASS 下，源码调试时看 dist/。"""
    for i, a in enumerate(sys.argv):
        if a == "--payload" and i + 1 < len(sys.argv):
            p = Path(sys.argv[i + 1])
            return p if p.exists() else None
    if getattr(sys, "frozen", False):
        p = Path(getattr(sys, "_MEIPASS", "")) / "payload.zip"
        return p if p.is_file() else None
    p = Path(__file__).resolve().parent.parent / "dist" / APP_TITLE
    return p if p.is_dir() else None


def payload_bytes(src: Path) -> int:
    if src.is_file():
        with zipfile.ZipFile(src) as z:
            return sum(i.file_size for i in z.infolist())
    return sum(f.stat().st_size for f in src.rglob("*") if f.is_file())


def free_bytes(path: Path) -> int:
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    free = ctypes.c_ulonglong(0)
    try:
        ctypes.WinDLL("kernel32").GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(str(p)), ctypes.byref(free), None, None)
    except OSError:
        return 0
    return free.value


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%.0f %s" if unit in ("B", "KB", "MB") else "%.1f %s") % (n, unit)
        n /= 1024.0
    return "%.0f B" % n


def writable(target: Path) -> bool:
    """能不能往这儿写 —— 选到 Program Files 时要提前说，别装到一半失败。"""
    p = target
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        probe = p / (".shiyi-write-test-%d" % os.getpid())
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def stop_running(wait: float = 8.0) -> bool:
    """把正在跑的那一份请出去，否则它的 exe 是锁着的。

    先按 runtime.json 里的端口和令牌礼貌地叫它退出；不理，再按 pid 硬来。
    """
    from .config import DATA_DIR
    rt_path = DATA_DIR / "runtime.json"
    try:
        rt = json.loads(rt_path.read_text("utf-8"))
    except (OSError, ValueError):
        return True

    port, token, pid = rt.get("port"), rt.get("token"), rt.get("pid")
    if port and token:
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://127.0.0.1:%d/api/quit" % port, data=b"{}",
                headers={"X-Shiyi-Token": token,
                         "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=3).read()
        except Exception:
            pass

    deadline = time.time() + wait
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.25)

    if pid:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        time.sleep(0.6)
    return not _alive(pid)


def _alive(pid) -> bool:
    if not pid:
        return False
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x1000, False, int(pid))     # QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong(0)
    k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_ulong)]
    k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))
    k32.CloseHandle(ctypes.c_void_p(h))
    return code.value == 259                          # STILL_ACTIVE


# ----------------------------------------------------------------- 注册表
def register(target: Path, size_bytes: int) -> None:
    import winreg
    exe = target / (APP_TITLE + ".exe")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        def s(name, value):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

        def d(name, value):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(value))

        s("DisplayName", DISPLAY_NAME)
        s("DisplayVersion", __version__)
        s("Publisher", DISPLAY_NAME)
        s("DisplayIcon", str(exe))
        s("InstallLocation", str(target))
        s("UninstallString", '"%s" --uninstall' % exe)
        s("QuietUninstallString", '"%s" --uninstall --quiet' % exe)
        s("URLInfoAbout", HOMEPAGE)
        s("InstallDate", time.strftime("%Y%m%d"))
        d("EstimatedSize", max(1, size_bytes // 1024))
        d("NoModify", 1)
        d("NoRepair", 1)


def unregister() -> None:
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass


# ----------------------------------------------------------------- 安装
def do_install(target: Path, desktop: bool, start_menu: bool, autostart: bool,
               report) -> Path:
    """报告函数签名是 report(0..1, 文字)。返回装好的 exe 路径。"""
    # 先查调用方给的参数，再查自己的打包：路径写不进是用户能当场改的，
    # 该优先说；「安装包缺东西」是打包出了问题，跟他选哪个目录无关。
    if not writable(target):
        raise RuntimeError("写不进 %s。换个位置，或者用默认的那个。" % target)

    src = payload()
    if src is None:
        raise RuntimeError("安装包里没找到程序本体")

    report(0.02, "正在检查是否有一份在运行……")
    if not stop_running():
        raise RuntimeError("有一份拾遗正在运行，且没能停下。手动退出托盘图标后再试。")

    old = installed_dir()
    if old and old.resolve() != target.resolve() and old.is_dir():
        report(0.06, "正在清理上一次装的位置……")
        _rmtree(old)

    report(0.08, "正在准备目录……")
    if target.is_dir():
        _rmtree(target, keep_root=True)
    target.mkdir(parents=True, exist_ok=True)

    report(0.12, "正在写入程序文件……")
    _copy_payload(src, target, report)

    exe = target / (APP_TITLE + ".exe")
    if not exe.is_file():
        raise RuntimeError("程序文件没写全，缺 %s" % exe.name)

    report(0.90, "正在登记到「应用和功能」……")
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    register(target, size)

    report(0.94, "正在创建快捷方式……")
    _shortcuts(exe, desktop, start_menu)

    if autostart:
        report(0.98, "正在设置开机自启……")
        _autostart(exe)

    report(1.0, "完成")
    return exe


def _copy_payload(src: Path, target: Path, report) -> None:
    lo, hi = 0.12, 0.88
    if src.is_file():
        with zipfile.ZipFile(src) as z:
            items = z.infolist()
            total = sum(i.file_size for i in items) or 1
            done = 0
            for i in items:
                z.extract(i, target)
                done += i.file_size
                report(lo + (hi - lo) * done / total, "正在写入 " + _tail(i.filename))
    else:
        files = [f for f in src.rglob("*") if f.is_file()]
        total = sum(f.stat().st_size for f in files) or 1
        done = 0
        for f in files:
            rel = f.relative_to(src)
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            done += f.stat().st_size
            report(lo + (hi - lo) * done / total, "正在写入 " + _tail(str(rel)))


def _tail(name: str) -> str:
    return name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:44]


def _rmtree(path: Path, keep_root: bool = False) -> None:
    if not path.exists():
        return
    if keep_root:
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
    else:
        shutil.rmtree(path, ignore_errors=True)


def _shortcuts(exe: Path, desktop: bool, start_menu: bool) -> list:
    from . import winintegration as wi
    made = []
    if start_menu:
        link = wi.start_menu_dir() / (APP_TITLE + ".lnk")
        if wi.create_shortcut(link, str(exe), "--tray", str(exe), str(exe.parent)):
            made.append(link)
    if desktop:
        link = wi.desktop_dir() / (APP_TITLE + ".lnk")
        if wi.create_shortcut(link, str(exe), "--tray", str(exe), str(exe.parent)):
            made.append(link)
    return made


def _autostart(exe: Path) -> None:
    import winreg
    with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
        winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ,
                          '"%s" --tray' % exe)


# ----------------------------------------------------------------- 卸载
def do_uninstall(purge_index: bool, report) -> Path | None:
    """撤掉登记、快捷方式、自启，并把索引按需删掉。

    程序目录留给 deferred_delete —— 自己正跑在里面，此刻删不掉。
    """
    report(0.1, "正在停止正在运行的拾遗……")
    stop_running()

    report(0.35, "正在删除快捷方式……")
    from . import winintegration as wi
    for link in (wi.start_menu_dir() / (APP_TITLE + ".lnk"),
                 wi.desktop_dir() / (APP_TITLE + ".lnk")):
        try:
            if link.is_file():
                link.unlink()
        except OSError:
            pass
    wi.set_autostart(False)

    report(0.55, "正在撤销登记……")
    unregister()

    if purge_index:
        report(0.75, "正在删除索引和设置……")
        from .config import DATA_DIR
        shutil.rmtree(DATA_DIR, ignore_errors=True)

    report(1.0, "完成")
    here = Path(sys.executable).parent if getattr(sys, "frozen", False) else None
    return here


def deferred_delete(folder: Path) -> bool:
    """脱离出去的 cmd：等本进程退干净，再删目录。

    两个坑：
    - 命令必须整条作为字符串交给 CreateProcess。用列表形式的话
      subprocess 会把带 & 和引号的那一段再包一层引号，cmd 解不开。
    - DETACHED_PROCESS 和 CREATE_NO_WINDOW 不能一起给，CreateProcess
      会直接判参数非法。脱离了控制台本来就不会有窗口，给一个就够。
    删一次不一定成（杀毒软件可能还按着文件），所以隔几秒再试一次。
    """
    if not folder or not folder.is_dir():
        return False
    d = str(folder)
    line = ('cmd /c ping 127.0.0.1 -n 4 >nul & rd /s /q "%s" & '
            'if exist "%s" ( ping 127.0.0.1 -n 6 >nul & rd /s /q "%s" )'
            % (d, d, d))
    try:
        subprocess.Popen(line, creationflags=0x00000008)   # DETACHED_PROCESS
        return True
    except OSError as e:
        console_write("没能安排删除 %s：%s\n" % (d, e), err=True)
        return False


# ================================================================= 界面
class Screen:
    OPTIONS, WORKING, DONE, ERROR = "options", "working", "done", "error"


class Wizard:
    """安装和卸载共用的一张窗：头部固定，中间按状态换内容。"""

    W, H = 560, 470

    def __init__(self, title: str, icon: str = "") -> None:
        self.win = U.Window(title, self.W, self.H, icon)
        self.win.on_paint = self._paint
        self.win.on_click = self._click
        self.win.on_key = self._key
        self.win.on_close = self._can_close
        self.screen = Screen.OPTIONS
        self.pct = 0.0
        self.note = ""
        self.error = ""
        self.result_exe = None

    # -------------------------------------------------------- 骨架
    def _can_close(self) -> bool:
        return self.screen != Screen.WORKING

    def _key(self, vk) -> None:
        if vk == VK_ESCAPE and self.screen != Screen.WORKING:
            self.win.close()
        elif vk == VK_RETURN and self.screen == Screen.OPTIONS:
            self.start()

    def _header(self, p, subtitle: str) -> None:
        s = p.px
        p.round_rect(s(40), s(36), s(54), s(54), s(15), SEAL)
        p.text("拾", s(40), s(37), s(54), s(54), 25, 0xFFFFFF, 600, DT_CENTER)
        p.text(APP_TITLE, s(112), s(38), s(300), s(32), 20, INK, 600)
        p.text(subtitle, s(112), s(70), s(340), s(20), 9.5, MUTED)

    def _footer_line(self, p, y: int) -> None:
        s = p.px
        p.line(s(40), s(y), s(self.W - 40), s(y), LINE, max(1.0, p.scale))

    def button(self, p, name, label, x, y, w, h, primary=True, enabled=True):
        s = p.px
        hot = self.win.zone(name, s(x), s(y), s(w), s(h)) if enabled else False
        down = self.win.pressed == name and enabled
        if primary:
            bg = SEAL if enabled else U.mix(SEAL, PAPER, 0.6)
            if down:
                bg = U.mix(SEAL, INK, 0.18)
            elif hot:
                bg = SEAL_HI
            p.round_rect(s(x), s(y), s(w), s(h), s(10), bg)
            fg = 0xFFFFFF
        else:
            bg = SURFACE_2 if not hot else SURFACE_3
            if down:
                bg = U.mix(SURFACE_3, INK, 0.06)
            p.round_rect(s(x), s(y), s(w), s(h), s(10), bg)
            p.round_outline(s(x), s(y), s(w), s(h), s(10), LINE_2,
                            max(1.0, p.scale))
            fg = INK_2 if enabled else FAINT
        p.text(label, s(x), s(y), s(w), s(h), 12, fg, 600, DT_CENTER)

    def checkbox(self, p, name, label, hint, x, y, checked) -> None:
        s = p.px
        row_h = 26
        hot = self.win.zone(name, s(x), s(y - 3), s(self.W - 2 * x), s(row_h + 6))
        box = 19
        by = y + (row_h - box) // 2
        if checked:
            p.round_rect(s(x), s(by), s(box), s(box), s(6), SEAL)
            p.check(s(x), s(by), s(box), 0xFFFFFF, 2.0 * p.scale)
        else:
            p.round_rect(s(x), s(by), s(box), s(box), s(6),
                         SURFACE if not hot else SURFACE_2)
            p.round_outline(s(x), s(by), s(box), s(box), s(6),
                            LINE_2 if not hot else MUTED, max(1.0, p.scale))
        p.text(label, s(x + box + 12), s(y), s(300), s(row_h), 10.5,
               INK_2 if not hot else INK, 400)
        if hint:
            w0 = p.measure(label, 10.5)[0]
            p.text(hint, s(x + box + 12) + w0 + s(10), s(y), s(300), s(row_h),
                   9, FAINT)

    # 三屏共用同一条基线：左边一枚 44 的圆，右边标题与说明，下面一张卡。
    ICON_Y, CARD_Y, FOOT_Y, BTN_Y = 140, 226, 392, 404

    def status(self, p, kind, title, subtitle) -> None:
        s = p.px
        y, d = self.ICON_Y, 44
        p.circle(s(40), s(y), s(d), SEAL_SOFT)
        if kind == "check":
            p.check(s(40), s(y), s(d), SEAL, 2.6 * p.scale)
        elif kind == "alert":
            p.round_rect(s(60), s(y + 11), s(3), s(14), s(2), SEAL)
            p.circle(s(60), s(y + 28), s(3), SEAL)
        else:                                    # 进度环
            sweep = 360.0 * max(0.03, min(1.0, self.pct))
            p.arc(s(40), s(y), s(d), SEAL, 3.0 * p.scale, -90.0, sweep)
        p.text(title, s(100), s(y + 2), s(410), s(40), 17, INK, 600)
        p.text(subtitle, s(100), s(y + 36), s(420), s(22), 9.5, MUTED,
               flags=DT_PATH_ELLIPSIS)

    def card(self, p, heading, lines, h=120) -> None:
        s = p.px
        y = self.CARD_Y
        p.round_rect(s(40), s(y), s(480), s(h), s(12), SURFACE)
        p.round_outline(s(40), s(y), s(480), s(h), s(12), LINE,
                        max(1.0, p.scale))
        p.text(heading, s(60), s(y + 18), s(240), s(22), 9, MUTED)
        for i, t in enumerate(lines):
            ly = y + 46 + i * 24
            p.circle(s(62), s(ly + 8), s(4), FAINT)
            p.text(t, s(78), s(ly), s(430), s(22), 9.5, INK_3)

    # -------------------------------------------------------- 工作线程
    def report(self, pct: float, note: str) -> None:
        self.pct, self.note = pct, note
        self.win.post()

    def work(self) -> None:
        raise NotImplementedError

    def start(self) -> None:
        import threading
        if self.screen != Screen.OPTIONS:
            return
        self.screen = Screen.WORKING
        self.pct, self.note = 0.0, "准备中……"
        self.win.refresh()

        def run():
            try:
                self.work()
                self.screen = Screen.DONE
            except Exception as e:                       # noqa: BLE001
                self.error = str(e) or e.__class__.__name__
                self.screen = Screen.ERROR
            self.win.post()

        threading.Thread(target=run, daemon=True).start()

    def run(self) -> int:
        return self.win.run()

    def _error_card(self, p, y) -> int:
        """朱砂淡底的错误卡，高度跟着文字长短走。返回卡片高度（设备像素）。"""
        s = p.px
        inner = s(436)
        th = p.para_height(self.error, inner, 9.5)
        h = max(s(72), th + s(40))
        p.round_rect(s(40), s(y), s(480), h, s(12), SEAL_SOFT)
        p.para(self.error, s(62), s(y) + (h - th) // 2, inner, 9.5,
               U.mix(SEAL, INK, 0.25))
        return h

    def _paint(self, p, w, h):
        raise NotImplementedError

    def _click(self, name):
        raise NotImplementedError


class SetupWizard(Wizard):
    """安装向导。"""

    def __init__(self, icon: str = "") -> None:
        super().__init__("安装拾遗", icon)
        self.target = installed_dir() or default_dir()
        self.desktop = True
        self.start_menu = True
        self.autostart = False
        self.upgrade = bool(installed_dir())
        src = payload()
        self.need = payload_bytes(src) if src else 0

    # -------------------------------------------------------- 画
    def _paint(self, p, w, h):
        s = p.px
        prev = installed_version()
        if self.upgrade and prev:
            sub = "Recollect · %s → %s" % (prev, __version__)
        else:
            sub = "Recollect · 版本 %s" % __version__
        self._header(p, sub)

        if self.screen == Screen.OPTIONS:
            self._paint_options(p)
        elif self.screen == Screen.WORKING:
            self.status(p, "ring", "升级中" if self.upgrade else "正在安装",
                        self.note)
            self.card(p, "接下来", self.NEXT_STEPS)
            self._footer_line(p, self.FOOT_Y)
            p.text("别关窗口，这通常只要几秒。", s(40), s(self.BTN_Y),
                   s(400), s(44), 9, FAINT)
        elif self.screen == Screen.DONE:
            self._paint_done(p)
        else:
            self._paint_error(p)

    def _paint_options(self, p):
        s = p.px
        p.text("把散落在硬盘里的每一件东西找回来。", s(40), s(112), s(480),
               s(24), 11, INK_2)

        p.text("安装到", s(40), s(156), s(200), s(20), 9, MUTED)

        hot = self.win.zone("path", s(40), s(180), s(388), s(42), U.IDC_ARROW)
        p.round_rect(s(40), s(180), s(388), s(42), s(10), SURFACE)
        p.round_outline(s(40), s(180), s(388), s(42), s(10), LINE,
                        max(1.0, p.scale))
        p.text(str(self.target), s(56), s(180), s(356), s(42), 10, INK_2,
               flags=DT_PATH_ELLIPSIS)
        self.button(p, "browse", "浏览", 440, 180, 80, 42, primary=False)

        free = free_bytes(self.target)
        ok_space = free == 0 or free > self.need * 1.4
        if not writable(self.target):
            msg, col = "这个位置写不进去，换一个（或者用默认的那个）。", SEAL
        elif not ok_space:
            msg, col = ("需要约 %s，这个盘只剩 %s。"
                        % (human(self.need), human(free)), SEAL)
        else:
            msg = "需要约 %s%s。不需要管理员权限。" % (
                human(self.need),
                "，该磁盘剩余 %s" % human(free) if free else "")
            col = MUTED
        p.text(msg, s(40), s(230), s(480), s(20), 9, col)

        self.checkbox(p, "cb_desktop", "创建桌面快捷方式", "", 40, 268,
                      self.desktop)
        self.checkbox(p, "cb_menu", "添加到开始菜单", "", 40, 300,
                      self.start_menu)
        self.checkbox(p, "cb_auto", "开机时自动启动", "在托盘待命", 40, 332,
                      self.autostart)

        self._footer_line(p, 392)
        p.text("不联网 · 不上传 · 只读你的文件", s(40), s(404), s(300), s(44),
               9, FAINT)
        self.button(p, "install", "升级" if self.upgrade else "安装",
                    402, 404, 118, 44,
                    enabled=writable(self.target) and ok_space and self.need > 0)

    NEXT_STEPS = (
        "启动后它待在系统托盘里，是一枚朱砂色的「拾」印。",
        "第一次会先问你扫哪几个文件夹，然后自己扫一遍。",
        "关掉窗口不等于退出 —— 它继续待命，随时能搜。",
    )

    def _paint_done(self, p):
        self.status(p, "check", "升级好了" if self.upgrade else "装好了",
                    str(self.target))
        self.card(p, "接下来", self.NEXT_STEPS)
        self._footer_line(p, self.FOOT_Y)
        self.button(p, "close", "完成", 268, self.BTN_Y, 110, 44, primary=False)
        self.button(p, "launch", "立即启动", 396, self.BTN_Y, 124, 44)

    def _paint_error(self, p):
        s = p.px
        self.status(p, "alert", "没能装上", "什么都没改动")
        y = self.CARD_Y
        ch = self._error_card(p, y)
        p.text("日志在 %USERPROFILE%\\.shiyi\\shiyi.log", s(40),
               s(y) + ch + s(14), s(480), s(20), 9, MUTED)
        self._footer_line(p, self.FOOT_Y)
        self.button(p, "close", "关闭", 268, self.BTN_Y, 110, 44, primary=False)
        self.button(p, "retry", "再试一次", 396, self.BTN_Y, 124, 44)

    # -------------------------------------------------------- 交互
    def _click(self, name):
        if self.screen == Screen.OPTIONS:
            if name == "browse":
                picked = U.pick_folder(self.win.hwnd, "把拾遗装到哪儿",
                                       str(self.target.parent))
                if picked:
                    p = Path(picked)
                    # 选到一个空目录就用它，否则在里面开一个同名文件夹
                    if p.name != APP_TITLE:
                        p = p / APP_TITLE
                    self.target = p
            elif name == "cb_desktop":
                self.desktop = not self.desktop
            elif name == "cb_menu":
                self.start_menu = not self.start_menu
            elif name == "cb_auto":
                self.autostart = not self.autostart
            elif name == "install":
                self.start()
            self.win.refresh()
        elif self.screen in (Screen.DONE, Screen.ERROR):
            if name == "retry":
                self.screen, self.error, self.pct = Screen.OPTIONS, "", 0.0
                self.win.refresh()
            elif name == "launch":
                self._launch()
                self.win.close()
            elif name == "close":
                self.win.close()

    def _launch(self) -> None:
        if not self.result_exe:
            return
        try:
            subprocess.Popen([str(self.result_exe), "--tray"],
                             cwd=str(self.result_exe.parent),
                             creationflags=0x00000008)      # DETACHED_PROCESS
        except OSError:
            pass

    def work(self) -> None:
        self.result_exe = do_install(self.target, self.desktop,
                                     self.start_menu, self.autostart,
                                     self.report)


class RemoveWizard(Wizard):
    """卸载向导。"""

    def __init__(self, icon: str = "") -> None:
        super().__init__("卸载拾遗", icon)
        self.purge = False
        self.folder = None
        self.index_size = self._index_size()

    @staticmethod
    def _index_size() -> int:
        try:
            from .config import DATA_DIR
            return sum(f.stat().st_size for f in DATA_DIR.rglob("*")
                       if f.is_file())
        except OSError:
            return 0

    def _paint(self, p, w, h):
        s = p.px
        self._header(p, "Recollect · 版本 %s" % __version__)

        if self.screen == Screen.OPTIONS:
            p.text("要把拾遗从这台电脑上移除吗？", s(40), s(112), s(480), s(24),
                   11, INK_2)
            p.round_rect(s(40), s(154), s(480), s(96), s(12), SURFACE)
            p.round_outline(s(40), s(154), s(480), s(96), s(12), LINE,
                            max(1.0, p.scale))
            p.text("会删掉", s(60), s(170), s(200), s(22), 9, MUTED)
            for i, t in enumerate(("程序文件和快捷方式", "开机自启设置")):
                y = 196 + i * 22
                p.circle(s(62), s(y + 8), s(4), FAINT)
                p.text(t, s(78), s(y), s(420), s(22), 9.5, INK_3)

            self.checkbox(p, "cb_purge", "同时删除索引和设置",
                          human(self.index_size) if self.index_size else "",
                          40, 272, self.purge)
            p.text("不勾的话索引留在 %USERPROFILE%\\.shiyi，重装能接着用。",
                   s(71), s(300), s(460), s(20), 9, FAINT)

            p.round_rect(s(40), s(332), s(480), s(40), s(10), SURFACE_2)
            p.text("你的原始文档一个字节都不会动。", s(56), s(332), s(450),
                   s(40), 9.5, INK_3)

            self._footer_line(p, 392)
            self.button(p, "close", "取消", 268, 404, 110, 44, primary=False)
            self.button(p, "remove", "卸载", 396, 404, 124, 44)
        elif self.screen == Screen.WORKING:
            self.status(p, "ring", "正在卸载", self.note)
            self._footer_line(p, self.FOOT_Y)
            p.text("马上就好。", s(40), s(self.BTN_Y), s(400), s(44), 9, FAINT)
        elif self.screen == Screen.DONE:
            self.status(p, "check", "卸载完成",
                        "索引和设置也一并删了。" if self.purge else
                        "索引还留在 %USERPROFILE%\\.shiyi，重装后接着用。")
            self.card(p, "留下的", (
                "你的文档、幻灯、PDF —— 一个字节都没动过。",
                "开始菜单和桌面的快捷方式已经撤掉。",
                "「应用和功能」里的登记也已经撤销。",
            ))
            self._footer_line(p, self.FOOT_Y)
            self.button(p, "close", "关闭", 402, self.BTN_Y, 118, 44)
        else:
            self.status(p, "alert", "没能卸干净", "程序文件还留在原处")
            self._error_card(p, self.CARD_Y)
            self._footer_line(p, self.FOOT_Y)
            self.button(p, "close", "关闭", 402, self.BTN_Y, 118, 44)

    def _click(self, name):
        if self.screen == Screen.OPTIONS:
            if name == "cb_purge":
                self.purge = not self.purge
            elif name == "remove":
                self.start()
            elif name == "close":
                self.win.close()
            self.win.refresh()
        elif name == "close":
            self.win.close()

    def work(self) -> None:
        self.folder = do_uninstall(self.purge, self.report)


# ----------------------------------------------------------------- 入口
def _icon() -> str:
    try:
        from . import web_dir
        p = web_dir() / "icon.ico"
        return str(p) if p.is_file() else ""
    except Exception:
        return ""


SILENT_HELP = """拾遗安装程序

  （直接双击）                打开安装界面
  --silent                   不出界面，按默认装好就退出
    --dir <路径>             装到别处，默认 %LOCALAPPDATA%\\Programs\\拾遗
    --no-desktop             不建桌面快捷方式
    --no-menu                不进开始菜单
    --autostart              顺便设成开机自启
    --launch                 装完直接起来
  --help                     看这段

静默安装成功返回 0，失败返回 1，并把原因打到标准错误。
装到当前用户名下，不需要管理员权限。
"""


def run_setup(argv=None) -> int:
    if sys.platform != "win32":
        print("安装程序只在 Windows 上有意义。")
        return 2
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--help" in argv or "/?" in argv:
        _say(SILENT_HELP)
        return 0

    if "--silent" in argv or "/S" in argv:
        return _silent(argv)

    U.dpi_aware()
    w = SetupWizard(_icon())
    w.run()
    return 0


INVALID_HANDLE = ctypes.c_void_p(-1).value
STD_OUT, STD_ERR = -11, -12


def _write_handle(k32, h, text: str) -> bool:
    """往一个句柄写字。控制台走 WriteConsoleW，文件和管道走 UTF-8 字节。

    分开写是必须的：控制台按当前代码页解释字节，这台机器上是 GBK，
    直接塞 UTF-8 进去中文全是乱码。
    """
    if not h or h == INVALID_HANDLE:
        return False
    n = ctypes.c_ulong(0)
    mode = ctypes.c_ulong(0)
    if k32.GetConsoleMode(ctypes.c_void_p(h), ctypes.byref(mode)):
        return bool(k32.WriteConsoleW(ctypes.c_void_p(h), text, len(text),
                                      ctypes.byref(n), None))
    data = text.encode("utf-8", "replace")
    return bool(k32.WriteFile(ctypes.c_void_p(h), data, len(data),
                              ctypes.byref(n), None))


def console_write(text: str, err: bool = False) -> bool:
    """把话说到调用方看得见的地方。说到了返回 True。

    安装程序是 --noconsole 打的 —— 双击时不该闪黑窗，但从命令行跑
    --silent 又得能回报结果。三种情形分别接住：

    - 调用方重定向到了文件或管道：标准句柄本来就有效，直接写
    - 从终端起的、没重定向：借父进程的控制台，写 CONOUT$
    - 双击起的：两条都不通，返回 False，由调用者去弹框

    早先的写法是无脑把 sys.stdout 换成 CONOUT$，结果 `--help > a.txt`
    既写不进文件、又接不上控制台，最后弹出一个没人能点的模态框挂死。
    """
    try:
        k32 = ctypes.WinDLL("kernel32")
        k32.GetStdHandle.restype = ctypes.c_void_p
        if _write_handle(k32, k32.GetStdHandle(STD_ERR if err else STD_OUT),
                         text):
            return True
        if not k32.AttachConsole(-1):                  # ATTACH_PARENT_PROCESS
            return False
        k32.CreateFileW.restype = ctypes.c_void_p
        h = k32.CreateFileW("CONOUT$", 0x40000000, 3, None, 3, 0, None)
        ok = _write_handle(k32, h, text)
        if h and h != INVALID_HANDLE:
            k32.CloseHandle(ctypes.c_void_p(h))
        return ok
    except OSError:
        return False


def _say(text: str) -> None:
    """说得出来就说，说不出来（多半是双击运行的）就弹个框。"""
    if not console_write(text + "\n"):
        U.message(None, text, "拾遗安装程序")


def _silent(argv: list) -> int:
    target = default_dir()
    for i, a in enumerate(argv):
        if a == "--dir" and i + 1 < len(argv):
            target = Path(argv[i + 1])
    try:
        exe = do_install(target,
                         desktop="--no-desktop" not in argv,
                         start_menu="--no-menu" not in argv,
                         autostart="--autostart" in argv,
                         report=lambda *_: None)
    except Exception as e:                                  # noqa: BLE001
        console_write("安装失败：%s\n" % e, err=True)
        return 1
    if "--launch" in argv:
        subprocess.Popen([str(exe), "--tray"], cwd=str(exe.parent),
                         creationflags=0x00000008)
    console_write("已安装到 %s\n" % target)
    return 0


def run_uninstall(argv=None) -> int:
    """拾遗.exe --uninstall。--quiet 时不出界面，直接卸。"""
    if sys.platform != "win32":
        return 2
    argv = list(sys.argv[1:] if argv is None else argv)
    quiet = "--quiet" in argv or "/S" in argv

    if quiet:
        folder = do_uninstall("--purge" in argv, lambda *_: None)
        deferred_delete(folder)
        return 0

    U.dpi_aware()
    w = RemoveWizard(_icon())
    w.run()
    if w.screen == Screen.DONE:
        deferred_delete(w.folder)
    return 0
