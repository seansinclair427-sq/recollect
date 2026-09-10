"""生成拾遗的图标，不依赖 Pillow。

用 Windows 自己的 GDI 把「拾」字画进内存位图，再手写 ICO 容器。
好处是字形来自系统字体，跟界面里的观感一致；也省掉一条构建依赖。
"""
from __future__ import annotations

import ctypes
import struct
import sys
from ctypes import wintypes
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "shiyi" / "web"
SIZES = (256, 128, 64, 48, 32, 24, 16)

SEAL = (0xB4, 0x45, 0x1F)          # 朱砂红，跟界面 --seal 一致
GLYPH = "拾"

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

AC_SRC_OVER = 0x00
TRANSPARENT = 1
DEFAULT_CHARSET = 1
CLEARTYPE_QUALITY = 5


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _render(size: int) -> bytearray:
    """返回 size*size 的 BGRA 像素（自上而下），画好底色、圆角和字。"""
    hdc = gdi32.CreateCompatibleDC(None)
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = size
    bi.bmiHeader.biHeight = -size          # 负数 = 自上而下
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0         # BI_RGB

    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bi), 0,
                                  ctypes.byref(bits), None, 0)
    if not hbmp:
        raise OSError("CreateDIBSection 失败")
    old = gdi32.SelectObject(hdc, hbmp)

    buf = (ctypes.c_ubyte * (size * size * 4)).from_address(bits.value)
    # 先整片填成印章色（GDI 不管 alpha，稍后自己补）
    for i in range(0, len(buf), 4):
        buf[i] = SEAL[2]        # B
        buf[i + 1] = SEAL[1]    # G
        buf[i + 2] = SEAL[0]    # R
        buf[i + 3] = 255

    # 画字
    height = -int(size * 0.62)
    font = gdi32.CreateFontW(
        height, 0, 0, 0, 600, 0, 0, 0, DEFAULT_CHARSET, 0, 0,
        CLEARTYPE_QUALITY, 0, "Microsoft YaHei UI")
    oldfont = gdi32.SelectObject(hdc, font)
    gdi32.SetBkMode(hdc, TRANSPARENT)
    gdi32.SetTextColor(hdc, 0x00FFFFFF)

    rect = wintypes.RECT(0, 0, size, size)
    # DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOCLIP
    user32.DrawTextW(hdc, GLYPH, -1, ctypes.byref(rect), 0x01 | 0x04 | 0x20 | 0x100)

    gdi32.SelectObject(hdc, oldfont)
    gdi32.DeleteObject(font)
    gdi32.GdiFlush()

    out = bytearray(buf)
    gdi32.SelectObject(hdc, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc)

    _round_corners(out, size)
    return out


def _round_corners(px: bytearray, size: int) -> None:
    """圆角 + 边缘抗锯齿。半径按尺寸缩放，跟界面上的 8px/34px 一致。"""
    r = max(2.0, size * 8.0 / 34.0)
    for y in range(size):
        for x in range(size):
            cov = _corner_coverage(x + 0.5, y + 0.5, size, r)
            if cov >= 1.0:
                continue
            i = (y * size + x) * 4
            a = int(255 * cov)
            px[i + 3] = a
            # 预乘一下，避免缩放时白字边缘发暗
            px[i] = px[i] * a // 255
            px[i + 1] = px[i + 1] * a // 255
            px[i + 2] = px[i + 2] * a // 255


def _corner_coverage(x: float, y: float, size: int, r: float) -> float:
    cx = r if x < r else (size - r if x > size - r else x)
    cy = r if y < r else (size - r if y > size - r else y)
    if cx == x and cy == y:
        return 1.0
    d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
    if d <= r - 0.7:
        return 1.0
    if d >= r + 0.7:
        return 0.0
    return max(0.0, min(1.0, (r + 0.7 - d) / 1.4))


def _bmp_entry(px: bytearray, size: int) -> bytes:
    """ICO 里的 BMP 条目：头是双倍高度，像素自下而上，外加一张 AND 掩码。"""
    hdr = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                      size * size * 4, 0, 0, 0, 0)
    rows = []
    for y in range(size - 1, -1, -1):
        rows.append(bytes(px[y * size * 4:(y + 1) * size * 4]))
    stride = ((size + 31) // 32) * 4
    mask = b"\x00" * (stride * size)
    return hdr + b"".join(rows) + mask


def build(path: Path) -> None:
    images = [(s, _render(s)) for s in SIZES]
    entries, blobs = [], []
    offset = 6 + 16 * len(images)
    for size, px in images:
        blob = _bmp_entry(px, size)
        entries.append(struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset))
        blobs.append(blob)
        offset += len(blob)
    path.write_bytes(b"".join([struct.pack("<HHH", 0, 1, len(images))]
                              + entries + blobs))


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("这个脚本用的是 Windows GDI，只能在 Windows 上跑。")
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "icon.ico"
    build(target)
    print("图标已生成：%s（%s，%d 字节）"
          % (target, "/".join(str(s) for s in SIZES), target.stat().st_size))
