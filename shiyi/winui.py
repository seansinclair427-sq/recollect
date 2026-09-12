"""一层很薄的 Win32 界面：纯 ctypes，GDI+ 画形状，GDI 画字。

为什么不用 tkinter：它在，但它长得不像这个产品。安装程序是用户见到的
第一屏，用一套跟界面无关的控件开场，等于先自我否定一次。

为什么形状走 GDI+、字走 GDI：GDI 画圆角是锯齿的，GDI+ 画字又糊
（它不走 ClearType）。两边各取所长，画在同一个 HDC 上。

控件是「立即模式」的：每次重绘时顺手把可点区域登记下来，
点击就拿上一帧的登记表去比对。没有控件树，也就没有控件树的麻烦。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

# ----------------------------------------------------------------- 调色板
# 跟 web/app.css 里的 --paper / --ink / --seal 是同一组值。
PAPER = 0xFAF7F2
SURFACE = 0xFFFEFB
SURFACE_2 = 0xF4F0E9
SURFACE_3 = 0xEBE5DB
INK = 0x1A1714
INK_2 = 0x4B433A
INK_3 = 0x6F6558
MUTED = 0x948A7C
FAINT = 0xB6AB9C
LINE = 0xE8E1D6
LINE_2 = 0xD8CFC1
SEAL = 0xB4451F
SEAL_HI = 0xC95226
SEAL_SOFT = 0xF6E3D9
GREEN = 0x4A7A4E

SANS = "Microsoft YaHei UI"

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        gdiplus = ctypes.WinDLL("gdiplus")
    except OSError:                      # 极老的系统，退回纯 GDI
        gdiplus = None
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
    except OSError:
        dwmapi = None
else:                                    # 让非 Windows 也能 import
    user32 = gdi32 = kernel32 = gdiplus = dwmapi = None

# ----------------------------------------------------------------- 常量
WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_CLOSE = 0x0010
WM_ERASEBKGND = 0x0014
WM_SETCURSOR = 0x0020
WM_GETMINMAXINFO = 0x0024
WM_KEYDOWN = 0x0100
WM_CHAR = 0x0102
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSELEAVE = 0x02A3
WM_APP = 0x8000
WM_TICK = WM_APP + 7

WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_VISIBLE = 0x10000000
WS_CLIPCHILDREN = 0x02000000
CS_DROPSHADOW = 0x00020000
CW_USEDEFAULT = -0x80000000
SW_SHOW = 5

IDC_ARROW = 32512
IDC_HAND = 32649
IDC_IBEAM = 32513
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010

DT_LEFT, DT_CENTER, DT_RIGHT = 0x0, 0x1, 0x2
DT_VCENTER, DT_WORDBREAK, DT_SINGLELINE = 0x4, 0x10, 0x20
DT_CALCRECT, DT_NOPREFIX = 0x400, 0x800
DT_PATH_ELLIPSIS, DT_END_ELLIPSIS = 0x4000, 0x8000

TRANSPARENT = 1
DEFAULT_CHARSET = 1
CLEARTYPE_QUALITY = 5

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWCP_ROUND = 2

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


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL),
                ("rcPaint", wintypes.RECT), ("fRestore", wintypes.BOOL),
                ("fIncUpdate", wintypes.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("hwndTrack", wintypes.HWND), ("dwHoverTime", wintypes.DWORD)]


class GdiplusStartupInput(ctypes.Structure):
    _fields_ = [("GdiplusVersion", ctypes.c_uint32),
                ("DebugEventCallback", ctypes.c_void_p),
                ("SuppressBackgroundThread", wintypes.BOOL),
                ("SuppressExternalCodecs", wintypes.BOOL)]


def _bind() -> None:
    """64 位下句柄是 8 字节，不声明 restype 会被截成 int。"""
    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.BeginPaint.restype = wintypes.HDC
    user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.LoadCursorW.restype = wintypes.HANDLE
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                  wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  wintypes.UINT]
    user32.SetCursor.restype = wintypes.HANDLE
    user32.SetCursor.argtypes = [wintypes.HANDLE]
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                wintypes.HBRUSH]
    user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                                 ctypes.POINTER(wintypes.RECT), wintypes.UINT]
    user32.InvalidateRect.argtypes = [wintypes.HWND,
                                      ctypes.POINTER(wintypes.RECT),
                                      wintypes.BOOL]
    user32.GetClientRect.argtypes = [wintypes.HWND,
                                     ctypes.POINTER(wintypes.RECT)]
    user32.ScreenToClient.argtypes = [wintypes.HWND,
                                      ctypes.POINTER(wintypes.POINT)]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UpdateWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = LRESULT
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR,
                                   wintypes.LPCWSTR, wintypes.UINT]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]

    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.GetDeviceCaps.restype = ctypes.c_int
    gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
    gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int,
                                             ctypes.c_int]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.CreateFontW.restype = wintypes.HFONT
    gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, wintypes.HDC,
                             ctypes.c_int, ctypes.c_int, wintypes.DWORD]

    if gdiplus:
        gdiplus.GdiplusStartup.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(GdiplusStartupInput), ctypes.c_void_p]
        gdiplus.GdipCreateFromHDC.argtypes = [wintypes.HDC,
                                              ctypes.POINTER(ctypes.c_void_p)]
        gdiplus.GdipCreateSolidFill.argtypes = [ctypes.c_uint32,
                                                ctypes.POINTER(ctypes.c_void_p)]
        gdiplus.GdipCreatePath.argtypes = [ctypes.c_int,
                                           ctypes.POINTER(ctypes.c_void_p)]
        gdiplus.GdipAddPathArc.argtypes = [
            ctypes.c_void_p, ctypes.c_float, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float, ctypes.c_float]
        gdiplus.GdipFillPath.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_void_p]
        gdiplus.GdipDrawPath.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_void_p]
        gdiplus.GdipCreatePen1.argtypes = [ctypes.c_uint32, ctypes.c_float,
                                           ctypes.c_int,
                                           ctypes.POINTER(ctypes.c_void_p)]
        gdiplus.GdipFillEllipse.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float]
        gdiplus.GdipDrawLine.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float]
        gdiplus.GdipFillRectangle.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float]
        gdiplus.GdipDrawArc.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_float, ctypes.c_float,
            ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float]
        gdiplus.GdipSetPenStartCap.argtypes = [ctypes.c_void_p, ctypes.c_int]
        gdiplus.GdipSetPenEndCap.argtypes = [ctypes.c_void_p, ctypes.c_int]
        gdiplus.GdipSetSmoothingMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        gdiplus.GdipSetPixelOffsetMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        gdiplus.GdipClosePathFigure.argtypes = [ctypes.c_void_p]
        for fn in ("GdipDeleteBrush", "GdipDeletePath", "GdipDeletePen",
                   "GdipDeleteGraphics"):
            getattr(gdiplus, fn).argtypes = [ctypes.c_void_p]


if sys.platform == "win32":
    _bind()

_gdip_token = ctypes.c_void_p()


def _gdip_start() -> bool:
    if not gdiplus:
        return False
    if _gdip_token.value:
        return True
    inp = GdiplusStartupInput(1, None, 0, 0)
    if gdiplus.GdiplusStartup(ctypes.byref(_gdip_token), ctypes.byref(inp), None):
        return False
    return True


def dpi_aware() -> None:
    """先试 per-monitor v2，不行退到系统级。高分屏上不做这步字会糊。"""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except (OSError, AttributeError):
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _rgb(c: int) -> int:
    """0xRRGGBB -> GDI 的 COLORREF（0x00BBGGRR）。"""
    return ((c & 0xFF) << 16) | (c & 0xFF00) | ((c >> 16) & 0xFF)


def _argb(c: int, alpha: int = 255) -> int:
    return (alpha << 24) | (c & 0xFFFFFF)


def mix(a: int, b: int, t: float) -> int:
    """在两个颜色之间取一点，用来做悬停和按下的状态。"""
    out = 0
    for sh in (16, 8, 0):
        ca, cb = (a >> sh) & 0xFF, (b >> sh) & 0xFF
        out |= int(round(ca + (cb - ca) * t)) << sh
    return out


# ----------------------------------------------------------------- 画笔
class Painter:
    """一帧的绘制上下文。形状走 GDI+，字走 GDI，共用一个 HDC。"""

    def __init__(self, hdc, scale: float) -> None:
        self.hdc = hdc
        self.scale = scale
        self._fonts: dict = {}
        self._g = None
        if _gdip_start():
            g = ctypes.c_void_p()
            if not gdiplus.GdipCreateFromHDC(hdc, ctypes.byref(g)):
                self._g = g
                gdiplus.GdipSetSmoothingMode(g, 4)       # AntiAlias
                gdiplus.GdipSetPixelOffsetMode(g, 2)     # Half

    def px(self, v: float) -> int:
        return int(round(v * self.scale))

    # -------------------------------------------------------- 形状
    def rect(self, x, y, w, h, color, alpha=255) -> None:
        if self._g:
            br = ctypes.c_void_p()
            gdiplus.GdipCreateSolidFill(_argb(color, alpha), ctypes.byref(br))
            gdiplus.GdipFillRectangle(self._g, br, ctypes.c_float(x),
                                      ctypes.c_float(y), ctypes.c_float(w),
                                      ctypes.c_float(h))
            gdiplus.GdipDeleteBrush(br)
            return
        brush = gdi32.CreateSolidBrush(_rgb(color))
        r = wintypes.RECT(int(x), int(y), int(x + w), int(y + h))
        user32.FillRect(self.hdc, ctypes.byref(r), brush)
        gdi32.DeleteObject(brush)

    def _path(self, x, y, w, h, r):
        p = ctypes.c_void_p()
        gdiplus.GdipCreatePath(0, ctypes.byref(p))
        d = r * 2.0
        f = ctypes.c_float
        gdiplus.GdipAddPathArc(p, f(x), f(y), f(d), f(d), f(180), f(90))
        gdiplus.GdipAddPathArc(p, f(x + w - d), f(y), f(d), f(d), f(270), f(90))
        gdiplus.GdipAddPathArc(p, f(x + w - d), f(y + h - d), f(d), f(d), f(0), f(90))
        gdiplus.GdipAddPathArc(p, f(x), f(y + h - d), f(d), f(d), f(90), f(90))
        gdiplus.GdipClosePathFigure(p)
        return p

    def round_rect(self, x, y, w, h, r, color, alpha=255) -> None:
        if not self._g or r <= 0:
            return self.rect(x, y, w, h, color, alpha)
        p = self._path(x, y, w, h, r)
        br = ctypes.c_void_p()
        gdiplus.GdipCreateSolidFill(_argb(color, alpha), ctypes.byref(br))
        gdiplus.GdipFillPath(self._g, br, p)
        gdiplus.GdipDeleteBrush(br)
        gdiplus.GdipDeletePath(p)

    def round_outline(self, x, y, w, h, r, color, width=1.0, alpha=255) -> None:
        if not self._g:
            return
        p = self._path(x + width / 2, y + width / 2, w - width, h - width, r)
        pen = ctypes.c_void_p()
        gdiplus.GdipCreatePen1(_argb(color, alpha), ctypes.c_float(width), 2,
                               ctypes.byref(pen))
        gdiplus.GdipDrawPath(self._g, pen, p)
        gdiplus.GdipDeletePen(pen)
        gdiplus.GdipDeletePath(p)

    def circle(self, x, y, d, color, alpha=255) -> None:
        if not self._g:
            return self.rect(x, y, d, d, color, alpha)
        br = ctypes.c_void_p()
        gdiplus.GdipCreateSolidFill(_argb(color, alpha), ctypes.byref(br))
        gdiplus.GdipFillEllipse(self._g, br, ctypes.c_float(x), ctypes.c_float(y),
                                ctypes.c_float(d), ctypes.c_float(d))
        gdiplus.GdipDeleteBrush(br)
        return None

    def line(self, x1, y1, x2, y2, color, width=1.0, alpha=255) -> None:
        if not self._g:
            return
        pen = ctypes.c_void_p()
        gdiplus.GdipCreatePen1(_argb(color, alpha), ctypes.c_float(width), 2,
                               ctypes.byref(pen))
        f = ctypes.c_float
        gdiplus.GdipDrawLine(self._g, pen, f(x1), f(y1), f(x2), f(y2))
        gdiplus.GdipDeletePen(pen)

    def arc(self, x, y, d, color, width=3.0, start=-90.0, sweep=360.0,
            alpha=255) -> None:
        """圆弧。用来做进度环 —— 端点收成圆角，转起来才不生硬。"""
        if not self._g or sweep <= 0:
            return
        pen = ctypes.c_void_p()
        gdiplus.GdipCreatePen1(_argb(color, alpha), ctypes.c_float(width), 2,
                               ctypes.byref(pen))
        gdiplus.GdipSetPenStartCap(pen, 2)          # LineCapRound
        gdiplus.GdipSetPenEndCap(pen, 2)
        f = ctypes.c_float
        gdiplus.GdipDrawArc(self._g, pen, f(x + width / 2), f(y + width / 2),
                            f(d - width), f(d - width), f(start), f(sweep))
        gdiplus.GdipDeletePen(pen)

    def check(self, x, y, size, color, width=2.0) -> None:
        """一个对勾：两段线，端点画圆补上接缝。"""
        if not self._g:
            return
        a = (x + size * 0.20, y + size * 0.52)
        b = (x + size * 0.42, y + size * 0.73)
        c = (x + size * 0.80, y + size * 0.28)
        self.line(a[0], a[1], b[0], b[1], color, width)
        self.line(b[0], b[1], c[0], c[1], color, width)
        self.circle(b[0] - width / 2, b[1] - width / 2, width, color)

    # -------------------------------------------------------- 字
    BOLD_FLOOR = 12.0          # 小于这个字号就不给粗体

    def font(self, size: float, weight: int = 400, face: str = SANS):
        # 雅黑没有 Semibold，GDI 只能自己把笔画抹粗。汉字本就密，
        # 「删」「露」「麟」这种字在 12pt 以下一抹就糊成一个黑块。
        # 所以小字一律压回常规字重，层次交给字号和颜色去分。
        if size < self.BOLD_FLOOR and weight > 500:
            weight = 500
        key = (round(size, 1), weight, face)
        f = self._fonts.get(key)
        if f is None:
            f = gdi32.CreateFontW(-self.px(size), 0, 0, 0, weight, 0, 0, 0,
                                  DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0,
                                  face)
            self._fonts[key] = f
        return f

    def text(self, s: str, x, y, w, h, size=10.5, color=INK, weight=400,
             align=DT_LEFT, face=SANS, flags=0) -> None:
        gdi32.SelectObject(self.hdc, self.font(size, weight, face))
        gdi32.SetBkMode(self.hdc, TRANSPARENT)
        gdi32.SetTextColor(self.hdc, _rgb(color))
        r = wintypes.RECT(int(x), int(y), int(x + w), int(y + h))
        user32.DrawTextW(self.hdc, s, -1, ctypes.byref(r),
                         align | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX | flags)

    def para(self, s: str, x, y, w, size=10.0, color=INK_3, weight=400,
             face=SANS) -> int:
        """多行正文，返回实际高度。"""
        gdi32.SelectObject(self.hdc, self.font(size, weight, face))
        gdi32.SetBkMode(self.hdc, TRANSPARENT)
        gdi32.SetTextColor(self.hdc, _rgb(color))
        r = wintypes.RECT(int(x), int(y), int(x + w), int(y + 4000))
        user32.DrawTextW(self.hdc, s, -1, ctypes.byref(r),
                         DT_LEFT | DT_WORDBREAK | DT_NOPREFIX | DT_CALCRECT)
        h = r.bottom - r.top
        r = wintypes.RECT(int(x), int(y), int(x + w), int(y + h))
        user32.DrawTextW(self.hdc, s, -1, ctypes.byref(r),
                         DT_LEFT | DT_WORDBREAK | DT_NOPREFIX)
        return h

    def para_height(self, s: str, w, size=10.0, weight=400, face=SANS) -> int:
        """折行后有多高 —— 先量再决定背景板多大。"""
        gdi32.SelectObject(self.hdc, self.font(size, weight, face))
        r = wintypes.RECT(0, 0, int(w), 4000)
        user32.DrawTextW(self.hdc, s, -1, ctypes.byref(r),
                         DT_LEFT | DT_WORDBREAK | DT_NOPREFIX | DT_CALCRECT)
        return r.bottom - r.top

    def measure(self, s: str, size=10.5, weight=400, face=SANS) -> tuple:
        gdi32.SelectObject(self.hdc, self.font(size, weight, face))
        r = wintypes.RECT(0, 0, 4000, 200)
        user32.DrawTextW(self.hdc, s, -1, ctypes.byref(r),
                         DT_LEFT | DT_SINGLELINE | DT_NOPREFIX | DT_CALCRECT)
        return r.right - r.left, r.bottom - r.top

    def done(self) -> None:
        for f in self._fonts.values():
            gdi32.DeleteObject(f)
        self._fonts.clear()
        if self._g:
            gdiplus.GdipDeleteGraphics(self._g)
            self._g = None


# ----------------------------------------------------------------- 窗口
class Window:
    """一个不可缩放的窗口，客户区完全自绘。

    标题栏交给系统画（这样圆角、阴影、拖动、关闭按钮都是原生的），
    再用 DWM 把它染成纸色，跟客户区接上。
    """

    _classes: set = set()

    def __init__(self, title: str, w: int, h: int, icon: str = "") -> None:
        dpi_aware()
        self.title = title
        self.scale = self._scale()
        self.cw, self.ch = int(w * self.scale), int(h * self.scale)
        self.hwnd = None
        self.hot = None            # 鼠标悬停在哪个区域
        self.pressed = None
        self.regions: list = []    # [(name, x, y, w, h, cursor)]
        self.on_paint = None       # callable(Painter, w, h)
        self.on_click = None       # callable(name)
        self.on_key = None         # callable(vk)
        self.on_char = None        # callable(ch)
        self.on_close = None       # callable() -> 允许关闭吗
        self.closing = False
        self._tracking = False
        self._proc = WNDPROC(self._wndproc)
        self._make(icon)

    @staticmethod
    def _scale() -> float:
        hdc = user32.GetDC(None)
        dpi = gdi32.GetDeviceCaps(hdc, 88) or 96      # LOGPIXELSX
        user32.ReleaseDC(None, hdc)
        return dpi / 96.0

    def _make(self, icon: str) -> None:
        cls = "ShiyiSetupWindow"
        hinst = kernel32.GetModuleHandleW(None)
        if cls not in Window._classes:
            wc = WNDCLASS()
            wc.style = CS_DROPSHADOW
            wc.lpfnWndProc = self._proc
            wc.hInstance = hinst
            wc.hCursor = user32.LoadCursorW(None, wintypes.LPCWSTR(IDC_ARROW))
            wc.hbrBackground = gdi32.CreateSolidBrush(_rgb(PAPER))
            wc.lpszClassName = cls
            if icon:
                wc.hIcon = user32.LoadImageW(None, icon, IMAGE_ICON, 0, 0,
                                             LR_LOADFROMFILE)
            if not user32.RegisterClassW(ctypes.byref(wc)):
                raise OSError("RegisterClassW 失败")
            Window._classes.add(cls)
            self._wc = wc                       # 别让回调被回收

        style = WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_CLIPCHILDREN
        r = wintypes.RECT(0, 0, self.cw, self.ch)
        user32.AdjustWindowRectEx(ctypes.byref(r), style, False, 0)
        ww, wh = r.right - r.left, r.bottom - r.top
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        self.hwnd = user32.CreateWindowExW(
            0, cls, self.title, style,
            (sw - ww) // 2, max(0, (sh - wh) // 2 - int(24 * self.scale)),
            ww, wh, None, None, hinst, None)
        if not self.hwnd:
            raise OSError("CreateWindowExW 失败：%d" % ctypes.get_last_error())
        self._dwm()
        user32.ShowWindow(self.hwnd, SW_SHOW)
        user32.UpdateWindow(self.hwnd)

    def _dwm(self) -> None:
        """把标题栏染成纸色、切圆角。老系统上静默失败即可。"""
        if not dwmapi:
            return
        def attr(a, value, size=4):
            try:
                v = ctypes.c_int(value)
                dwmapi.DwmSetWindowAttribute(self.hwnd, a, ctypes.byref(v), size)
            except OSError:
                pass
        attr(DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
        attr(DWMWA_CAPTION_COLOR, _rgb(PAPER))
        attr(DWMWA_TEXT_COLOR, _rgb(INK_3))

    # -------------------------------------------------------- 区域登记
    def zone(self, name, x, y, w, h, cursor=IDC_HAND) -> bool:
        """登记一个可点区域，返回鼠标此刻是否在上面。"""
        self.regions.append((name, x, y, w, h, cursor))
        return self.hot == name

    def hit(self, x, y):
        for name, rx, ry, rw, rh, cur in reversed(self.regions):
            if rx <= x < rx + rw and ry <= y < ry + rh:
                return name, cur
        return None, IDC_ARROW

    def refresh(self) -> None:
        if self.hwnd:
            user32.InvalidateRect(self.hwnd, None, False)

    def close(self) -> None:
        self.closing = True
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def post(self, arg: int = 0) -> None:
        """从后台线程叫醒界面。"""
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_TICK, arg, 0)

    def run(self) -> int:
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return 0

    # -------------------------------------------------------- 消息
    def _wndproc(self, hwnd, msg, wp, lp):
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_PAINT:
            self._paint(hwnd)
            return 0
        if msg == WM_MOUSEMOVE:
            x, y = ctypes.c_short(lp & 0xFFFF).value, ctypes.c_short(lp >> 16).value
            name, _ = self.hit(x, y)
            if not self._tracking:
                t = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), 2, hwnd, 0)
                user32.TrackMouseEvent(ctypes.byref(t))
                self._tracking = True
            if name != self.hot:
                self.hot = name
                self.refresh()
            return 0
        if msg == WM_MOUSELEAVE:
            self._tracking = False
            if self.hot is not None:
                self.hot = None
                self.refresh()
            return 0
        if msg == WM_SETCURSOR:
            if (lp & 0xFFFF) == 1:            # HTCLIENT
                p = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(p))
                user32.ScreenToClient(hwnd, ctypes.byref(p))
                _, cur = self.hit(p.x, p.y)
                user32.SetCursor(user32.LoadCursorW(None, wintypes.LPCWSTR(cur)))
                return 1
            return user32.DefWindowProcW(hwnd, msg, wp, lp)
        if msg == WM_LBUTTONDOWN:
            x, y = ctypes.c_short(lp & 0xFFFF).value, ctypes.c_short(lp >> 16).value
            self.pressed, _ = self.hit(x, y)
            self.refresh()
            return 0
        if msg == WM_LBUTTONUP:
            x, y = ctypes.c_short(lp & 0xFFFF).value, ctypes.c_short(lp >> 16).value
            name, _ = self.hit(x, y)
            was, self.pressed = self.pressed, None
            self.refresh()
            if name and name == was and self.on_click:
                self.on_click(name)
            return 0
        if msg == WM_KEYDOWN:
            if self.on_key:
                self.on_key(wp)
            return 0
        if msg == WM_CHAR:
            if self.on_char:
                self.on_char(wp)
            return 0
        if msg == WM_TICK:
            self.refresh()
            return 0
        if msg == WM_CLOSE:
            if self.on_close and not self.closing and not self.on_close():
                return 0                      # 正在干活，不许关
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _paint(self, hwnd) -> None:
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        rc = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rc))
        w, h = rc.right, rc.bottom

        # 双缓冲：先画进内存位图，再一次贴上去，避免闪
        mem = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
        old = gdi32.SelectObject(mem, bmp)

        p = Painter(mem, self.scale)
        p.rect(0, 0, w, h, PAPER)
        self.regions = []
        if self.on_paint:
            self.on_paint(p, w, h)
        p.done()

        gdi32.BitBlt(hdc, 0, 0, w, h, mem, 0, 0, 0x00CC0020)   # SRCCOPY
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.EndPaint(hwnd, ctypes.byref(ps))


# ----------------------------------------------------------------- 对话框
def pick_folder(hwnd, title: str, start: str = "") -> str:
    """选目录。用老的 SHBrowseForFolder —— 它不需要 COM 初始化，
    在 PyInstaller 打出来的进程里最不容易出意外。"""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32")

    class BROWSEINFO(ctypes.Structure):
        _fields_ = [("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p),
                    ("pszDisplayName", wintypes.LPWSTR),
                    ("lpszTitle", wintypes.LPCWSTR), ("ulFlags", wintypes.UINT),
                    ("lpfn", ctypes.c_void_p), ("lParam", wintypes.LPARAM),
                    ("iImage", ctypes.c_int)]

    BFFM_INITIALIZED, BFFM_SETSELECTIONW = 1, 0x467
    CB = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.UINT,
                            wintypes.LPARAM, wintypes.LPARAM)

    def _cb(hw, msg, lp, data):
        if msg == BFFM_INITIALIZED and start:
            user32.SendMessageW(hw, BFFM_SETSELECTIONW, 1,
                                ctypes.cast(ctypes.c_wchar_p(start),
                                            ctypes.c_void_p))
        return 0

    cb = CB(_cb)
    buf = ctypes.create_unicode_buffer(260)
    bi = BROWSEINFO()
    bi.hwndOwner = hwnd
    bi.pszDisplayName = ctypes.cast(buf, wintypes.LPWSTR)
    bi.lpszTitle = title
    bi.ulFlags = 0x0041                      # RETURNONLYFSDIRS | NEWDIALOGSTYLE
    bi.lpfn = ctypes.cast(cb, ctypes.c_void_p)

    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
    if not pidl:
        return ""
    out = ctypes.create_unicode_buffer(260)
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    ok = shell32.SHGetPathFromIDListW(pidl, out)
    ole32.CoTaskMemFree(ctypes.c_void_p(pidl))
    return out.value if ok else ""


def message(hwnd, text: str, title: str, flags: int = 0x40) -> int:
    return user32.MessageBoxW(hwnd, text, title, flags)
