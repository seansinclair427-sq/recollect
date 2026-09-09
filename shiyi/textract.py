"""正文抽取：docx / pptx / xlsx / pdf / 纯文本 / 代码 / 老版 Office。

全部只用标准库。Office 2007+ 就是 ZIP + XML，自己解比装 python-docx 快得多，
也省掉一条依赖。老版 .doc/.ppt/.xls 是 OLE 复合文档，做不到精确解析，
用一个「可读串」启发式兜底，并把状态标成 legacy 让界面能提示。
"""
from __future__ import annotations

import io
import os
import re
import zipfile

from . import pdftext
from .config import kind_of

MAX_ZIP_MEMBER = 40_000_000


# ----------------------------------------------------------------- 工具
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(xml: str) -> str:
    return _TAG_RE.sub("", xml)


def _unescape(s: str) -> str:
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
             .replace("&apos;", "'").replace("&#10;", "\n").replace("&amp;", "&"))


def _collapse(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t ]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _zip_read(zf: zipfile.ZipFile, name: str) -> str:
    info = zf.getinfo(name)
    if info.file_size > MAX_ZIP_MEMBER:
        return ""
    return zf.read(name).decode("utf-8", "ignore")


# ----------------------------------------------------------------- OOXML
def _docx(data: bytes) -> str:
    parts = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        targets = ["word/document.xml"]
        targets += sorted(n for n in names
                          if re.fullmatch(r"word/(header|footer|footnotes|endnotes)\d*\.xml", n))
        targets += sorted(n for n in names if n.startswith("word/comments"))
        for n in targets:
            if n not in names:
                continue
            xml = _zip_read(zf, n)
            # 段落 / 换行 / 制表转成真正的分隔符，再剥标签
            xml = re.sub(r"</w:p>", "\n", xml)
            xml = re.sub(r"<w:br[^>]*/?>", "\n", xml)
            xml = re.sub(r"<w:tab[^>]*/?>", "\t", xml)
            xml = re.sub(r"</w:tc>", "\t", xml)
            xml = re.sub(r"</w:tr>", "\n", xml)
            parts.append(_unescape(_strip_tags(xml)))
    return _collapse("\n".join(parts))


def _pptx(data: bytes) -> str:
    """按幻灯片顺序抽取，并带上「第 N 页」标记——搜到时能直接说出在第几页。"""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()

        def slide_no(n: str) -> int:
            m = re.search(r"(\d+)\.xml$", n)
            return int(m.group(1)) if m else 0

        slides = sorted((n for n in names
                         if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=slide_no)
        notes = {slide_no(n): n for n in names
                 if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", n)}
        for n in slides:
            i = slide_no(n)
            xml = _zip_read(zf, n)
            xml = re.sub(r"</a:p>", "\n", xml)
            xml = re.sub(r"<a:br[^>]*/?>", "\n", xml)
            txt = _unescape(_strip_tags(xml)).strip()
            block = ["【第 %d 页】" % i, txt] if txt else []
            if i in notes:
                nt = _unescape(_strip_tags(re.sub(r"</a:p>", "\n", _zip_read(zf, notes[i])))).strip()
                if nt:
                    block.append("（备注）" + nt)
            if block:
                out.append("\n".join(block))
    return _collapse("\n\n".join(out))


def _xlsx(data: bytes) -> str:
    """共享字符串 + 内联字符串。表格里的文字都在这两处。"""
    chunks = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        if "xl/sharedStrings.xml" in names:
            xml = _zip_read(zf, "xl/sharedStrings.xml")
            for m in re.finditer(r"<si>(.*?)</si>", xml, re.S):
                t = _unescape(_strip_tags(m.group(1))).strip()
                if t:
                    chunks.append(t)
        for n in sorted(x for x in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", x)):
            xml = _zip_read(zf, n)
            for m in re.finditer(r'<c[^>]*t="(?:inlineStr|str)"[^>]*>(.*?)</c>', xml, re.S):
                t = _unescape(_strip_tags(m.group(1))).strip()
                if t:
                    chunks.append(t)
    # 去掉海量重复单元格，只留一次
    seen, uniq = set(), []
    for c in chunks:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return _collapse("\n".join(uniq))


# ----------------------------------------------------------------- 老 Office
def _legacy_ole(data: bytes) -> str:
    """.doc/.ppt/.xls 兜底：抽 UTF-16LE 与 ASCII 的可读串。"""
    out = []
    # UTF-16LE 连续可读串
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00|[\x00-\xff][\x30-\x9f]){8,}", data):
        try:
            s = m.group(0).decode("utf-16-le", "ignore")
        except Exception:
            continue
        s = "".join(c for c in s if c.isprintable() or c in "\n\t")
        if len(s.strip()) >= 6:
            out.append(s.strip())
    if sum(len(x) for x in out) < 200:
        for m in re.finditer(rb"[\x20-\x7e]{10,}", data):
            out.append(m.group(0).decode("ascii", "ignore"))
    txt = _collapse("\n".join(out))
    # 去掉一望而知的结构噪声
    txt = re.sub(r"(?m)^[A-Za-z0-9+/=]{40,}$", "", txt)
    return txt.strip()


# ----------------------------------------------------------------- 纯文本
def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    for enc in ("gb18030", "big5", "utf-16", "latin-1"):
        try:
            s = data.decode(enc)
            if s.count("�") / max(1, len(s)) < 0.02:
                return s
        except Exception:
            continue
    return data.decode("utf-8", "replace")


def _looks_binary(data: bytes) -> bool:
    head = data[:8192]
    if b"\x00" in head:
        return True
    nonprint = sum(1 for b in head if b < 9 or (13 < b < 32))
    return nonprint / max(1, len(head)) > 0.10


# ----------------------------------------------------------------- 入口
_OOXML = {".docx": _docx, ".pptx": _pptx, ".xlsx": _xlsx,
          ".docm": _docx, ".pptm": _pptx, ".xlsm": _xlsx}
_LEGACY = {".doc", ".ppt", ".xls"}


def extract(path: str, data: bytes | None = None, limit: int = 400_000) -> tuple:
    """返回 (正文, 状态)。

    状态: ok / empty / scanned / no-tounicode / garbled / legacy /
          binary / toobig / unsupported / error:<msg>
    """
    ext = os.path.splitext(path)[1].lower()
    kind = kind_of(path)
    try:
        if data is None:
            with open(path, "rb") as fh:
                data = fh.read()
    except Exception as exc:
        return "", "error:" + type(exc).__name__

    try:
        if ext in _OOXML:
            if not data.startswith(b"PK"):
                return "", "error:NotZip"
            txt = _OOXML[ext](data)
            return txt[:limit], ("ok" if txt else "empty")
        if ext == ".pdf":
            txt, st = pdftext.extract_ex(data)
            return txt[:limit], st
        if ext in _LEGACY:
            txt = _legacy_ole(data)
            return txt[:limit], ("legacy" if txt else "empty")
        if kind in ("doc", "code", "sheet") or ext in (".srt", ".vtt", ".po"):
            if _looks_binary(data):
                return "", "binary"
            txt = _collapse(_decode_text(data))
            return txt[:limit], ("ok" if txt else "empty")
    except zipfile.BadZipFile:
        return "", "error:BadZip"
    except Exception as exc:
        return "", "error:" + type(exc).__name__
    return "", "unsupported"
