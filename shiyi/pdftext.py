"""纯标准库 PDF 正文抽取。

不依赖 pypdf / mupdf。做法：
  1. 扫出所有间接对象（含压缩对象流 ObjStm）；
  2. 解 FlateDecode（含 PNG predictor）；
  3. 把 /ToUnicode CMap 解析成「码位 -> 字符」表，按字体资源名绑定；
  4. 在内容流里跑一个小型 PostScript 词法器，抓 Tj / TJ 并按当前字体解码。

对 Word / PowerPoint / LaTeX 导出的中文 PDF 有效（Identity-H + ToUnicode）。
扫描件（纯图像）没有正文，返回空串，由调用方降级为只索引文件名。
"""
from __future__ import annotations

import re
import time
import zlib

MAX_TIME = 8.0          # 单个 PDF 最多解析秒数
MAX_CHARS = 400_000

_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj", re.S)
_STREAM_RE = re.compile(rb"stream\r?\n?(.*?)\r?\n?endstream", re.S)


# ----------------------------------------------------------------- 解码
def _undo_png_predictor(data: bytes, columns: int, colors: int, bpc: int) -> bytes:
    bpp = max(1, (colors * bpc) // 8)
    rowlen = (columns * colors * bpc + 7) // 8
    out = bytearray()
    prev = bytearray(rowlen)
    i, n = 0, len(data)
    while i < n:
        ft = data[i]
        i += 1
        row = bytearray(data[i:i + rowlen])
        if len(row) < rowlen:
            row.extend(b"\0" * (rowlen - len(row)))
        i += rowlen
        if ft == 1:
            for j in range(bpp, rowlen):
                row[j] = (row[j] + row[j - bpp]) & 0xFF
        elif ft == 2:
            for j in range(rowlen):
                row[j] = (row[j] + prev[j]) & 0xFF
        elif ft == 3:
            for j in range(rowlen):
                left = row[j - bpp] if j >= bpp else 0
                row[j] = (row[j] + ((left + prev[j]) >> 1)) & 0xFF
        elif ft == 4:
            for j in range(rowlen):
                a = row[j - bpp] if j >= bpp else 0
                b = prev[j]
                c = prev[j - bpp] if j >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[j] = (row[j] + pr) & 0xFF
        out.extend(row)
        prev = row
    return bytes(out)


def _int_after(pattern: bytes, blob: bytes, default: int) -> int:
    m = re.search(pattern, blob)
    return int(m.group(1)) if m else default


def _decode_stream(dict_bytes: bytes, raw: bytes) -> bytes | None:
    if b"FlateDecode" not in dict_bytes:
        # 未压缩的内容流也要收
        return raw if b"/Filter" not in dict_bytes else None
    try:
        data = zlib.decompress(raw)
    except Exception:
        try:
            data = zlib.decompressobj().decompress(raw)
        except Exception:
            return None
    if _int_after(rb"/Predictor\s+(\d+)", dict_bytes, 0) >= 10:
        try:
            data = _undo_png_predictor(
                data,
                _int_after(rb"/Columns\s+(\d+)", dict_bytes, 1),
                _int_after(rb"/Colors\s+(\d+)", dict_bytes, 1),
                _int_after(rb"/BitsPerComponent\s+(\d+)", dict_bytes, 8),
            )
        except Exception:
            pass
    return data


# ----------------------------------------------------------------- 对象表
def _collect_objects(data: bytes) -> dict:
    """objnum -> (字典部分, 已解压的流 或 None)"""
    objs: dict = {}
    for m in _OBJ_RE.finditer(data):
        num = int(m.group(1))
        body = m.group(3)
        sm = _STREAM_RE.search(body)
        if sm:
            head = body[: sm.start()]
            objs[num] = (head, _decode_stream(head, sm.group(1)))
        else:
            objs[num] = (body, None)

    # 展开对象流：字体 / 资源字典常常藏在里面
    for num, (head, stream) in list(objs.items()):
        if stream is None or b"/ObjStm" not in head:
            continue
        n = _int_after(rb"/N\s+(\d+)", head, 0)
        first = _int_after(rb"/First\s+(\d+)", head, 0)
        if not n or not first:
            continue
        try:
            pairs = stream[:first].split()
            for k in range(n):
                onum = int(pairs[2 * k])
                off = int(pairs[2 * k + 1])
                end = (int(pairs[2 * k + 3]) + first) if 2 * k + 3 < len(pairs) else len(stream)
                if onum not in objs:
                    objs[onum] = (stream[first + off:end], None)
        except Exception:
            continue
    return objs


# ----------------------------------------------------------------- CMap
_BFCHAR_RE = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE_RE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)
_HEX_RE = re.compile(rb"<([0-9A-Fa-f\s]*)>")


def _is_junk(ch: str) -> bool:
    """子集字体的 ToUnicode 常把部分码位映到控制符 / 私用区，那不是真文字。"""
    o = ord(ch)
    return (
        (o < 0x20 and ch not in "\n\t")
        or o == 0x7F
        or 0x80 <= o <= 0x9F
        or o == 0xFFFD
        or 0xE000 <= o <= 0xF8FF
        or 0xFFF0 <= o <= 0xFFFF
    )


def _scrub(s: str) -> str:
    return "".join(c for c in s if not _is_junk(c))


def _hex_to_str(h: bytes) -> str:
    h = re.sub(rb"\s", b"", h)
    if len(h) % 2:
        h += b"0"
    try:
        raw = bytes.fromhex(h.decode("ascii")).decode("utf-16-be", "ignore")
    except Exception:
        return ""
    return _scrub(raw)


def _parse_cmap(stream: bytes) -> dict:
    cmap: dict = {}
    for blk in _BFCHAR_RE.findall(stream):
        toks = _HEX_RE.findall(blk)
        for i in range(0, len(toks) - 1, 2):
            try:
                src = int(re.sub(rb"\s", b"", toks[i]), 16)
            except Exception:
                continue
            cmap[src] = _hex_to_str(toks[i + 1])
    for blk in _BFRANGE_RE.findall(stream):
        # 形式 A: <lo> <hi> <dst>      形式 B: <lo> <hi> [<d1> <d2> ...]
        pat = rb"<([0-9A-Fa-f\s]+)>\s*<([0-9A-Fa-f\s]+)>\s*(\[.*?\]|<[0-9A-Fa-f\s]*>)"
        for m in re.finditer(pat, blk, re.S):
            try:
                lo = int(re.sub(rb"\s", b"", m.group(1)), 16)
                hi = int(re.sub(rb"\s", b"", m.group(2)), 16)
            except Exception:
                continue
            if not 0 <= hi - lo <= 65535:
                continue
            dst = m.group(3)
            if dst.startswith(b"["):
                for k, it in enumerate(_HEX_RE.findall(dst)):
                    if lo + k <= hi:
                        cmap[lo + k] = _hex_to_str(it)
            else:
                base = _hex_to_str(dst[1:-1])
                if not base:
                    continue
                head, tail = base[:-1], ord(base[-1])
                for k in range(hi - lo + 1):
                    if tail + k <= 0x10FFFF:
                        cmap[lo + k] = head + chr(tail + k)
    return cmap


def _build_font_maps(objs: dict) -> tuple[dict, dict]:
    """资源名(F1) -> CMap，以及资源名 -> 是否双字节编码。"""
    obj_cmap: dict = {}
    obj_two: dict = {}
    for num, (head, _s) in objs.items():
        if b"/Font" not in head and b"/ToUnicode" not in head:
            continue
        obj_two[num] = bool(re.search(rb"Identity-[HV]", head)) or b"/Type0" in head
        m = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", head)
        if not m:
            continue
        src = objs.get(int(m.group(1)))
        if src and src[1]:
            cm = _parse_cmap(src[1])
            if cm:
                obj_cmap[num] = cm
                if max(cm) > 255:
                    obj_two[num] = True

    name_cmap: dict = {}
    name_two: dict = {}
    for _num, (head, _s) in objs.items():
        for fm in re.finditer(rb"/Font\s*<<(.*?)>>", head, re.S):
            for pm in re.finditer(rb"/([A-Za-z0-9#+.\-]+)\s+(\d+)\s+\d+\s+R", fm.group(1)):
                nm, fo = pm.group(1), int(pm.group(2))
                if fo in obj_cmap:
                    name_cmap.setdefault(nm, {}).update(obj_cmap[fo])
                if obj_two.get(fo):
                    name_two[nm] = True
    return name_cmap, name_two


# ----------------------------------------------------------------- 内容流
_ESC = {b"n": 10, b"r": 13, b"t": 9, b"b": 8, b"f": 12, b"(": 40, b")": 41, b"\\": 92}


def _unescape_literal(s: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(s)
    while i < n:
        c = s[i:i + 1]
        if c == b"\\" and i + 1 < n:
            nx = s[i + 1:i + 2]
            if nx in _ESC:
                out.append(_ESC[nx]); i += 2; continue
            if nx.isdigit():
                j, oct_ = i + 1, b""
                while j < n and len(oct_) < 3 and s[j:j + 1].isdigit():
                    oct_ += s[j:j + 1]; j += 1
                out.append(int(oct_, 8) & 0xFF)
                i = j; continue
            if nx in (b"\n", b"\r"):
                i += 2; continue
            out += nx; i += 2; continue
        out += c
        i += 1
    return bytes(out)


def _decode_show(raw: bytes, is_hex: bool, cmap, twobyte: bool) -> str:
    if is_hex:
        h = re.sub(rb"[^0-9A-Fa-f]", b"", raw)
        if len(h) % 2:
            h += b"0"
        try:
            data = bytes.fromhex(h.decode("ascii"))
        except Exception:
            return ""
    else:
        data = _unescape_literal(raw)

    if cmap:
        step = 2 if (twobyte or max(cmap) > 255) else 1
        out = []
        for i in range(0, len(data) - step + 1, step):
            code = int.from_bytes(data[i:i + step], "big")
            ch = cmap.get(code)
            if ch is None and step == 2:
                ch = cmap.get(data[i])
            out.append(ch or "")
        return "".join(out)
    if twobyte:
        return _scrub(data.decode("utf-16-be", "ignore"))
    return _scrub(data.decode("latin-1", "ignore"))


_TOKEN_RE = re.compile(
    rb"\((?:\\.|[^\\()])*\)"          # 字面字符串
    rb"|<[0-9A-Fa-f\s]*>"             # 十六进制字符串
    rb"|/[^\s/\[\]<>(){}]*"           # 名字
    rb"|-?\d*\.?\d+"                  # 数字
    rb"|Tf|Tj|TJ|Td|TD|Tm|T\*|TL|Ts|Tz|Tc|Tw|BT|ET|cm|q|Q|\'|\"|\[|\]",
    re.S,
)
_SHOW_OPS = (b"Tj", b"'", b'"')


def _num(tok: bytes) -> float:
    try:
        return float(tok)
    except Exception:
        return 0.0


def _extract_content(stream: bytes, name_cmap: dict, name_two: dict) -> str:
    """抽正文，并按文字在页面上的坐标重排。

    很多中文 PDF 逐字定位（每个字一次 Td），不跟踪坐标就会得到「一字一行、
    顺序错乱」的结果。这里维护文本矩阵的平移量，把每段文字记成 (y, x, s)，
    最后按 y 降序、x 升序还原成人类阅读顺序。
    """
    runs: list = []          # (行号, x, 文本)
    cur_cmap = None
    cur_two = False
    pending: list = []
    x = y = 0.0              # 当前文本位置
    lx = ly = 0.0            # 行起点（Td 相对于它累加）
    leading = 0.0

    def emit(s: str) -> None:
        if s:
            runs.append((round(y, 1), round(x, 1), s))

    for m in _TOKEN_RE.finditer(stream):
        t = m.group(0)
        if t == b"BT":
            x = y = lx = ly = 0.0
            pending.clear()
        elif t == b"Tf":
            for p in reversed(pending):
                if p.startswith(b"/"):
                    cur_cmap = name_cmap.get(p[1:])
                    cur_two = name_two.get(p[1:], False)
                    break
            pending.clear()
        elif t == b"TL":
            if pending:
                leading = _num(pending[-1])
            pending.clear()
        elif t == b"Tm":
            if len(pending) >= 6:
                lx, ly = _num(pending[-2]), _num(pending[-1])
                x, y = lx, ly
            pending.clear()
        elif t in (b"Td", b"TD"):
            if len(pending) >= 2:
                dx, dy = _num(pending[-2]), _num(pending[-1])
                if t == b"TD":
                    leading = -dy
                lx += dx
                ly += dy
                x, y = lx, ly
            pending.clear()
        elif t == b"T*":
            ly -= leading
            x, y = lx, ly
            pending.clear()
        elif t in _SHOW_OPS:
            if t != b"Tj":          # ' 和 " 先换行
                ly -= leading
                x, y = lx, ly
            for p in reversed(pending):
                if p[:1] in (b"(", b"<"):
                    emit(_decode_show(p[1:-1], p[:1] == b"<", cur_cmap, cur_two))
                    break
            pending.clear()
        elif t == b"TJ":
            buf = []
            for p in pending:
                if p[:1] in (b"(", b"<"):
                    buf.append(_decode_show(p[1:-1], p[:1] == b"<", cur_cmap, cur_two))
            emit("".join(buf))
            pending.clear()
        elif t == b"ET":
            pending.clear()
        else:
            pending.append(t)
            if len(pending) > 600:
                del pending[:300]

    if not runs:
        return ""
    return _layout(runs)


def _layout(runs: list) -> str:
    """把 (y, x, text) 片段按阅读顺序拼回去。"""
    import bisect

    ys = sorted({r[0] for r in runs})
    # 相差极小的 y 归成同一行（同一行内的字常有 0.x 的抖动）
    lines_y: list = []
    for v in ys:
        if not lines_y or v - lines_y[-1] > 1.5:
            lines_y.append(v)

    def bucket(v: float) -> float:
        i = bisect.bisect_left(lines_y, v)
        if i == 0:
            return lines_y[0]
        if i >= len(lines_y):
            return lines_y[-1]
        lo, hi = lines_y[i - 1], lines_y[i]
        return lo if (v - lo) <= (hi - v) else hi

    grouped: dict = {}
    for gy, gx, s in runs:
        grouped.setdefault(bucket(gy), []).append((gx, s))

    out = []
    for gy in sorted(grouped, reverse=True):
        row = sorted(grouped[gy], key=lambda p: p[0])
        out.append("".join(s for _x, s in row))
    return "\n".join(out)


# ----------------------------------------------------------------- 入口
def extract(data: bytes) -> str:
    """返回 PDF 正文；失败、加密或纯图像时返回空串。"""
    return extract_ex(data)[0]


def extract_ex(data: bytes) -> tuple:
    """返回 (正文, 状态)。状态用于在界面上区分「扫描件」和「解析失败」。

    状态取值: ok / scanned / no-tounicode / encrypted / garbled / notpdf / fail
    """
    t0 = time.time()
    if not data.startswith(b"%PDF"):
        return "", "notpdf"
    if b"/Encrypt" in data[-4096:] or b"/Encrypt " in data:
        pass  # 多数只是空口令加密，仍值得一试
    try:
        objs = _collect_objects(data)
    except Exception:
        return "", "fail"
    if not objs:
        return "", "fail"
    try:
        name_cmap, name_two = _build_font_maps(objs)
    except Exception:
        name_cmap, name_two = {}, {}

    chunks: list = []
    total = 0
    for num in sorted(objs):
        if time.time() - t0 > MAX_TIME or total > MAX_CHARS:
            break
        head, stream = objs[num]
        if not stream:
            continue
        if b"/Image" in head or b"/ObjStm" in head or b"/XRef" in head:
            continue
        if b"BT" not in stream and b"Tj" not in stream and b"TJ" not in stream:
            continue
        try:
            txt = _extract_content(stream, name_cmap, name_two)
        except Exception:
            continue
        if txt.strip():
            chunks.append(txt)
            total += len(txt)

    text = "\n".join(chunks)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    clean = _sanity(text)
    if clean:
        return clean, "ok"
    if not chunks:
        # 没有任何文字绘制指令 —— 扫描件或纯图排版
        if data.count(b"/Image") > 0:
            return "", "scanned"
        return "", "empty"
    if not name_cmap:
        return "", "no-tounicode"
    return "", "garbled"


def _sanity(text: str) -> str:
    """乱码守卫。

    只统计「确凿的坏字符」——控制字符、替换符、私用区、未分配码位——
    而不是去枚举好字符。早期版本用白名单，结果把一份满是 ∶．（）的
    生物试卷整篇误杀了。
    """
    s = _scrub(text).strip()
    if len(s) < 8:
        return ""
    bad = sum(1 for c in s if _is_junk(c))
    return s if bad / len(s) <= 0.30 else ""
