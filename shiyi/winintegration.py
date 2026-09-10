"""Windows 集成：开机自启、开始菜单 / 桌面快捷方式、卸载。

开机自启走 HKCU 的 Run 键（winreg 是标准库，不用碰 COM）。
快捷方式用 PowerShell 的 WScript.Shell 建，比用 ctypes 手搓 IShellLink 稳。
所有写入都在当前用户名下，不需要管理员权限。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("shiyi.win")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "Shiyi"
APP_TITLE = "拾遗"


def supported() -> bool:
    return sys.platform == "win32"


# ----------------------------------------------------------------- 启动命令
def launch_command() -> str:
    """拿到「怎么再启动我一次」的命令行。

    打包成 exe 之后是 exe 自己；源码运行时是 pythonw + -m shiyi，
    用 pythonw 才不会每次开机弹一个黑色控制台窗口。
    """
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    runner = pyw if pyw.is_file() else exe
    pkg_parent = Path(__file__).resolve().parent.parent
    return '"%s" -m shiyi --tray' % runner if _importable(pkg_parent) else \
           '"%s" "%s" --tray' % (runner, pkg_parent / "shiyi" / "__main__.py")


def _importable(parent: Path) -> bool:
    """包能不能直接 import —— 装过就能，源码目录得靠 cwd。"""
    try:
        import shiyi  # noqa: F401
        return True
    except Exception:
        return parent.is_dir()


# ----------------------------------------------------------------- 开机自启
def autostart_enabled() -> bool:
    if not supported():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
        return True
    except OSError:
        return False


def set_autostart(enable: bool) -> bool:
    if not supported():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if enable:
                cmd = launch_command()
                if getattr(sys, "frozen", False):
                    cmd = cmd + " --tray"
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
                log.info("已设置开机自启：%s", cmd)
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                    log.info("已取消开机自启")
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        log.exception("改开机自启失败")
        return False


# ----------------------------------------------------------------- 快捷方式
def _ps(script: str) -> bool:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=40,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode:
            log.warning("PowerShell 出错：%s", (r.stderr or "").strip()[:300])
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        log.exception("调用 PowerShell 失败")
        return False


def create_shortcut(link: Path, target: str, args: str = "",
                    icon: str = "", workdir: str = "") -> bool:
    link.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(%s)" % _q(link),
        "$s.TargetPath = %s" % _q(target),
    ]
    if args:
        parts.append("$s.Arguments = %s" % _q(args))
    if icon:
        parts.append("$s.IconLocation = %s" % _q(icon))
    if workdir:
        parts.append("$s.WorkingDirectory = %s" % _q(workdir))
    parts += ["$s.Description = %s" % _q("拾遗 —— 本地作品档案馆"), "$s.Save()"]
    return _ps("; ".join(parts))


def _q(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def start_menu_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / \
        "Microsoft" / "Windows" / "Start Menu" / "Programs"


def desktop_dir() -> Path:
    p = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
    return p if p.is_dir() else Path.home()


def _shortcut_target() -> tuple:
    """返回 (target, args, workdir)。"""
    if getattr(sys, "frozen", False):
        return sys.executable, "--tray", str(Path(sys.executable).parent)
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    runner = str(pyw if pyw.is_file() else exe)
    root = Path(__file__).resolve().parent.parent
    return runner, "-m shiyi --tray", str(root)


def install(desktop: bool = True, start_menu: bool = True,
            autostart: bool = False) -> dict:
    """建快捷方式、按需设开机自启。返回做了哪些事。"""
    if not supported():
        return {"ok": False, "reason": "只支持 Windows"}
    target, args, workdir = _shortcut_target()
    from . import web_dir
    icon = str(web_dir() / "icon.ico")
    done = {"ok": True, "shortcuts": [], "autostart": False}

    if start_menu:
        link = start_menu_dir() / (APP_TITLE + ".lnk")
        if create_shortcut(link, target, args, icon, workdir):
            done["shortcuts"].append(str(link))
    if desktop:
        link = desktop_dir() / (APP_TITLE + ".lnk")
        if create_shortcut(link, target, args, icon, workdir):
            done["shortcuts"].append(str(link))
    if autostart:
        done["autostart"] = set_autostart(True)
    return done


def uninstall(remove_index: bool = False) -> dict:
    """撤掉快捷方式和自启。索引默认保留 —— 删数据要人明确点头。"""
    removed = []
    for link in (start_menu_dir() / (APP_TITLE + ".lnk"),
                 desktop_dir() / (APP_TITLE + ".lnk")):
        try:
            if link.is_file():
                link.unlink()
                removed.append(str(link))
        except OSError:
            log.exception("删快捷方式失败：%s", link)
    set_autostart(False)

    index_removed = False
    if remove_index:
        from .config import DATA_DIR
        import shutil
        try:
            shutil.rmtree(DATA_DIR, ignore_errors=True)
            index_removed = not DATA_DIR.exists()
        except OSError:
            log.exception("删索引目录失败")
    return {"ok": True, "removed": removed, "index_removed": index_removed}
