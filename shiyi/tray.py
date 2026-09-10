"""系统托盘图标 —— 纯 ctypes 调 Win32，不引入 pystray / Pillow。

只做一件事：在通知区域放一个图标，左键触发主操作，右键弹菜单，
并且能弹气泡提示。消息循环占用主线程，HTTP 服务跑在后台线程里。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:                                   # 让非 Windows 也能 import（测试用）
    user32 = shell32 = kernel32 = None

# ----------------------------------------------------------------- 常量
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_CLOSE = 0x0010

NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
NIIF_NONE, NIIF_INFO, NIIF_WARNING, NIIF_ERROR = 0, 1, 2, 3

IMAGE_ICON = 1
LR_LOADFROMFILE, LR_DEFAULTSIZE, LR_SHARED = 0x0010, 0x0040, 0x8000

MF_STRING, MF_SEPARATOR, MF_GRAYED, MF_CHECKED = 0x0000, 0x0800, 0x0001, 0x0008
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0002, 0x0100, 0x0080

IDI_APPLICATION = 32512
CW_USEDEFAULT = -0x80000000
WS_OVERLAPPED = 0x00000000


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
    ]


def _bind() -> None:
    """把用到的函数签名声明清楚 —— 64 位下不声明会截断句柄。"""
    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                  wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  wintypes.UINT]
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.TrackPopupMenu.restype = ctypes.c_int
    user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      wintypes.HWND, wintypes.LPVOID]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                          ctypes.POINTER(NOTIFYICONDATA)]


class MenuItem:
    __slots__ = ("label", "action", "enabled", "default", "separator")

    def __init__(self, label="", action=None, *, enabled=True,
                 default=False, separator=False):
        self.label = label
        self.action = action
        self.enabled = enabled
        self.default = default
        self.separator = separator


SEPARATOR = MenuItem(separator=True)


class TrayIcon:
    """一个托盘图标。menu 是一个返回 MenuItem 列表的函数，每次右键都重新问，
    这样菜单项能反映当前状态（比如「扫描中…」要变灰）。"""

    def __init__(self, title: str, icon_path: Path | str | None,
                 menu_factory, on_activate=None):
        if sys.platform != "win32":
            raise RuntimeError("托盘只在 Windows 上可用")
        _bind()
        self.title = title[:127]
        self.icon_path = str(icon_path) if icon_path else None
        self.menu_factory = menu_factory
        self.on_activate = on_activate
        self._hwnd = None
        self._hicon = None
        self._nid = None
        self._alive = False
        self._items: list = []
        # 回调必须自己拿住引用，否则会被 GC 掉，Windows 回调时就崩了
        self._wndproc = WNDPROC(self._on_message)
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")

    # ------------------------------------------------------------- 生命周期
    def _create_window(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        cls = WNDCLASS()
        cls.lpfnWndProc = self._wndproc
        cls.hInstance = hinst
        cls.lpszClassName = "ShiyiTrayWindow"
        if not user32.RegisterClassW(ctypes.byref(cls)):
            err = ctypes.get_last_error()
            if err != 1410:                     # 已注册过，无所谓
                raise ctypes.WinError(err)
        self._cls = cls                          # 同样要拿住
        # 普通窗口但从不显示：TrackPopupMenu 需要一个能成为前台的窗口，
        # 纯消息窗口（HWND_MESSAGE）做不到，菜单会点不掉。
        self._hwnd = user32.CreateWindowExW(
            0, "ShiyiTrayWindow", self.title, WS_OVERLAPPED,
            CW_USEDEFAULT, CW_USEDEFAULT, 0, 0, None, None, hinst, None)
        if not self._hwnd:
            raise ctypes.WinError(ctypes.get_last_error())

    def _load_icon(self):
        if self.icon_path and Path(self.icon_path).is_file():
            h = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0,
                                  LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                return h
        return user32.LoadIconW(None, wintypes.LPCWSTR(IDI_APPLICATION))

    def _make_nid(self, flags: int) -> NOTIFYICONDATA:
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self._hicon
        nid.szTip = self.title
        return nid

    def show(self) -> None:
        self._create_window()
        self._hicon = self._load_icon()
        self._nid = self._make_nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid))
        self._alive = True

    def set_tooltip(self, text: str) -> None:
        self.title = text[:127]
        if not self._alive:
            return
        nid = self._make_nid(NIF_TIP)
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def notify(self, title: str, message: str, level: str = "info") -> None:
        """气泡提示。扫描完成之类的事件用它，不打断人。"""
        if not self._alive:
            return
        nid = self._make_nid(NIF_INFO)
        nid.szInfoTitle = title[:63]
        nid.szInfo = message[:255]
        nid.dwInfoFlags = {"info": NIIF_INFO, "warn": NIIF_WARNING,
                           "error": NIIF_ERROR, "none": NIIF_NONE}.get(level, NIIF_INFO)
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def remove(self) -> None:
        if self._alive and self._nid is not None:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
        self._alive = False

    def stop(self) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)

    # ------------------------------------------------------------- 菜单
    def _popup(self) -> None:
        items = list(self.menu_factory())
        self._items = items
        hmenu = user32.CreatePopupMenu()
        for i, it in enumerate(items, start=1):
            if it.separator:
                user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                continue
            flags = MF_STRING | (0 if it.enabled else MF_GRAYED)
            user32.AppendMenuW(hmenu, flags, i, it.label)
            if it.default:
                user32.SetMenuDefaultItem(hmenu, i, 0)

        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        # 不先抢前台的话，菜单会一直赖着不消失 —— Win32 的老毛病
        user32.SetForegroundWindow(self._hwnd)
        cmd = user32.TrackPopupMenu(
            hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
            pt.x, pt.y, 0, self._hwnd, None)
        user32.PostMessageW(self._hwnd, 0, 0, 0)
        user32.DestroyMenu(hmenu)

        if 1 <= cmd <= len(items):
            item = items[cmd - 1]
            if item.action and item.enabled:
                self._safe(item.action)

    def _safe(self, fn) -> None:
        try:
            fn()
        except Exception:
            import logging
            logging.getLogger("shiyi").exception("托盘菜单动作出错")

    # ------------------------------------------------------------- 消息
    def _on_message(self, hwnd, msg, wparam, lparam) -> int:
        if msg == WM_TRAYICON:
            low = lparam & 0xFFFF
            if low in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                if self.on_activate:
                    self._safe(self.on_activate)
            elif low == WM_RBUTTONUP:
                self._popup()
            return 0
        if msg == self._taskbar_created and self._alive:
            # 资源管理器重启过，图标没了，重新加回去
            shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid))
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            self.remove()
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self) -> None:
        """阻塞式消息循环，跑在主线程。"""
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self.remove()


def available() -> bool:
    return sys.platform == "win32"
