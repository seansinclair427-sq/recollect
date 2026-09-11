"""给安卓版生成图标，复用桌面版那套 GDI 渲染。

自适应图标的前景要留安全边距：系统会把外圈裁掉，所以「拾」字只占中间
约 60%，否则圆形图标上会被啃掉一角。
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_icon  # noqa: E402  复用 GDI 渲染

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "android" / "app" / "src" / "main" / "res"

# 传统图标（带底色圆角方块）
LEGACY = {"mipmap-mdpi": 48, "mipmap-hdpi": 72, "mipmap-xhdpi": 96,
          "mipmap-xxhdpi": 144, "mipmap-xxxhdpi": 192}
# 自适应图标前景：108dp 画布，中间 72dp 才是安全区
FOREGROUND = {"mipmap-mdpi": 108, "mipmap-hdpi": 162, "mipmap-xhdpi": 216,
              "mipmap-xxhdpi": 324, "mipmap-xxxhdpi": 432}


def png(path: Path, px: bytearray, size: int) -> None:
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            i = (y * size + x) * 4
            raw += bytes((px[i + 2], px[i + 1], px[i], px[i + 3]))   # BGRA -> RGBA

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b""))


def transparent_foreground(size: int) -> bytearray:
    """只画白色的「拾」，底色交给 adaptive-icon 的 background 层。"""
    glyph = int(size * 0.42)                 # 108dp 画布里约 45dp，落在安全区内
    px = make_icon._render(glyph)            # 朱砂底 + 白字
    out = bytearray(size * size * 4)         # 全透明
    off = (size - glyph) // 2
    for y in range(glyph):
        for x in range(glyph):
            s = (y * glyph + x) * 4
            # 底是朱砂、字是白：白得越多，说明越是字
            b, g, r, a = px[s], px[s + 1], px[s + 2], px[s + 3]
            if a == 0:
                continue
            whiteness = min(b, g, r)         # 朱砂的蓝通道很低，白字三通道都高
            if whiteness < 40:
                continue
            d = ((y + off) * size + (x + off)) * 4
            out[d] = out[d + 1] = out[d + 2] = 255
            out[d + 3] = whiteness
    return out


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("用的是 Windows GDI，只能在 Windows 上跑。")
    for folder, size in LEGACY.items():
        px = make_icon._render(size)
        png(RES / folder / "ic_launcher.png", px, size)
        png(RES / folder / "ic_launcher_round.png", px, size)
    for folder, size in FOREGROUND.items():
        png(RES / folder / "ic_fore.png", transparent_foreground(size), size)
    n = sum(1 for _ in RES.rglob("ic_*.png"))
    print("安卓图标已生成：%d 个 PNG -> %s" % (n, RES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
