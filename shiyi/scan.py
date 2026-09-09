"""扫描与增量索引。

流程：枚举 -> 与库比对（size+mtime）-> 只处理新增/变更 -> 线程池抽正文
-> 单线程写库。删除的文件同步清掉。
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

from .config import (Config, IGNORE_FILE_NAMES, IGNORE_FILE_PREFIXES,
                     MAX_DIR_TEXT_BYTES, TEXTUAL_KINDS, kind_of,
                     looks_minified, skip_content)
from . import store, textract

WORKERS = 8
BATCH = 400


class Progress:
    """扫描进度，供 CLI 与网页轮询。"""

    def __init__(self) -> None:
        self.phase = "idle"
        self.seen = 0
        self.total = 0
        self.done = 0
        self.added = 0
        self.updated = 0
        self.removed = 0
        self.errors = 0
        self.current = ""
        self.started = 0.0
        self.finished = 0.0
        self.message = ""

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["elapsed"] = (self.finished or time.time()) - self.started if self.started else 0
        return d


# OneDrive / iCloud 的「云端占位符」：文件在资源管理器里看得见，本地却没有
# 内容。一旦打开就会触发下载。用户机器上 OneDrive 有 78% 是这种文件，
# 傻乎乎地读一遍等于把整个网盘拖下来。所以：只记录元数据，不碰内容。
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_MASK = (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN
              | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)


def is_cloud_only(st) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & CLOUD_MASK)


# ----------------------------------------------------------------- 枚举
def enumerate_files(cfg: Config, progress: Progress | None = None):
    """产出 (path, size, mtime, root_label, cloud_only)。"""
    from .config import DATA_DIR
    selfdir = os.path.normcase(str(DATA_DIR).rstrip("\\/"))
    for root in cfg.roots:
        root = os.path.abspath(root)
        label = os.path.basename(root.rstrip("\\/")) or root
        stack = [root]
        while stack:
            cur = stack.pop()
            try:
                it = os.scandir(cur)
            except (PermissionError, OSError):
                continue
            with it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if (not cfg.ignored_dir(e.name)
                                    and os.path.normcase(e.path) != selfdir):
                                stack.append(e.path)
                            continue
                        if not e.is_file(follow_symlinks=False):
                            continue
                        n = e.name
                        if n in IGNORE_FILE_NAMES or n.startswith(IGNORE_FILE_PREFIXES):
                            continue
                        st = e.stat()
                        if st.st_size > cfg.max_file_bytes:
                            continue
                        if progress is not None:
                            progress.seen += 1
                        yield e.path, st.st_size, st.st_mtime, label, is_cloud_only(st)
                    except (PermissionError, OSError):
                        continue


# ----------------------------------------------------------------- 抽取
def _fingerprint(text: str) -> str:
    norm = re.sub(r"\s+", "", text)[:200_000]
    if len(norm) < 40:
        return ""
    return hashlib.blake2b(norm.encode("utf-8", "ignore"), digest_size=12).hexdigest()


# 只有「体积约等于正文长度」的裸文本才参与目录预算。
# docx / pptx / xlsx / pdf 是压缩包，一个 4MB 的 docx 可能只有两万字正文，
# 拿体积当正文来算会把你自己的文件夹整个误判掉（期中复盘就被误伤过一次）。
BUDGETED_KINDS = {"code"}
BUDGETED_EXTS = {".txt", ".log", ".md", ".csv", ".tsv"}
EXEMPT_EXTS = {".docx", ".pptx", ".xlsx", ".doc", ".ppt", ".xls", ".pdf",
               ".docm", ".pptm", ".xlsm", ".rtf", ".odt"}


def _bulk_text_dirs(jobs: list) -> set:
    """找出「裸文本成吨」的目录。

    钢铁雄心的 wiki 转储、Mixly 里塞的 PortableGit 文档、Python 标准库测试——
    都是一个目录里堆着几兆纯文本。它们不是你写的，却能把索引撑到近 1GB。
    文件名照常入索引（你还是能按名字找到），只是不抽正文。
    """
    tally: dict = {}
    for path, size, _m, _r, _c in jobs:
        ext = os.path.splitext(path)[1].lower()
        if ext in EXEMPT_EXTS:
            continue
        if kind_of(path) in BUDGETED_KINDS or ext in BUDGETED_EXTS:
            d = os.path.dirname(path)
            tally[d] = tally.get(d, 0) + size
    return {d for d, n in tally.items() if n > MAX_DIR_TEXT_BYTES}


def _process(job: tuple, cfg: Config, bulk: set = frozenset()) -> dict:
    path, size, mtime, root, cloud = job
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    kind = kind_of(path)
    body, status, fp = "", None, ""
    if cloud:
        status = "cloud"
    elif (ext not in EXEMPT_EXTS and kind in TEXTUAL_KINDS
            and os.path.dirname(path) in bulk):
        status = "skip:bulk"
    elif cfg.index_content and kind in TEXTUAL_KINDS:
        skip = skip_content(path, size, kind)
        if skip:
            status = "skip:" + skip
        else:
            body, status = textract.extract(path, limit=cfg.max_text_bytes)
            if body and kind == "code" and looks_minified(body):
                body, status = "", "skip:minified"
            if body:
                fp = _fingerprint(body)
    return {
        "path": path, "parent": os.path.dirname(path), "name": name,
        "ext": ext, "kind": kind, "size": size, "mtime": mtime, "root": root,
        "text_status": status, "text_len": len(body), "fp": fp, "body": body,
    }


# ----------------------------------------------------------------- 主流程
def scan(con, cfg: Config, progress: Progress | None = None, full: bool = False) -> dict:
    p = progress or Progress()
    p.phase = "enumerate"
    p.started = time.time()
    p.seen = p.done = p.added = p.updated = p.removed = p.errors = 0
    t0 = time.time()

    existing = {
        r["path"]: (r["id"], r["size"], r["mtime"])
        for r in con.execute("SELECT id, path, size, mtime FROM files")
    }

    jobs, keep = [], set()
    for path, size, mtime, root, cloud in enumerate_files(cfg, p):
        keep.add(path)
        prev = existing.get(path)
        if prev and not full and prev[1] == size and abs(prev[2] - mtime) < 1.0:
            continue
        jobs.append((path, size, mtime, root, cloud))

    bulk = _bulk_text_dirs(jobs)

    gone = [existing[pth][0] for pth in existing.keys() - keep]
    if gone:
        con.executemany("DELETE FROM files WHERE id=?", [(i,) for i in gone])
        con.executemany("DELETE FROM files_fts WHERE rowid=?", [(i,) for i in gone])
        con.commit()
        p.removed = len(gone)

    p.phase = "index"
    p.total = len(jobs)
    batch: list = []

    def flush() -> None:
        if not batch:
            return
        for rec in batch:
            prev = existing.get(rec["path"])
            if prev:
                fid = prev[0]
                con.execute(
                    "UPDATE files SET parent=?,name=?,ext=?,kind=?,size=?,mtime=?,root=?,"
                    "text_status=?,text_len=?,fp=?,indexed_at=? WHERE id=?",
                    (rec["parent"], rec["name"], rec["ext"], rec["kind"], rec["size"],
                     rec["mtime"], rec["root"], rec["text_status"], rec["text_len"],
                     rec["fp"], time.time(), fid),
                )
                con.execute("DELETE FROM files_fts WHERE rowid=?", (fid,))
                p.updated += 1
            else:
                cur = con.execute(
                    "INSERT INTO files(path,parent,name,ext,kind,size,mtime,root,"
                    "text_status,text_len,fp,indexed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rec["path"], rec["parent"], rec["name"], rec["ext"], rec["kind"],
                     rec["size"], rec["mtime"], rec["root"], rec["text_status"],
                     rec["text_len"], rec["fp"], time.time()),
                )
                fid = cur.lastrowid
                p.added += 1
            con.execute(
                "INSERT INTO files_fts(rowid, name, body) VALUES(?,?,?)",
                (fid, _searchable_name(rec["name"], rec["path"]), rec["body"]),
            )
        con.commit()
        batch.clear()

    # 分块提交，不要用 pool.map(jobs)：那会一次性把 15 万个任务全排进队列，
    # 抽取线程比写库快得多，抽出来的正文会全部堆在内存里等着被消费，
    # 十几万个文件足以把内存吃光、把机器拖垮。这里一次只放 BATCH 个进去。
    if jobs:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for start in range(0, len(jobs), BATCH):
                chunk = jobs[start:start + BATCH]
                for rec in pool.map(lambda j: _safe(j, cfg, p, bulk), chunk):
                    if rec is None:
                        continue
                    batch.append(rec)
                    p.done += 1
                    p.current = rec["name"]
                flush()
    flush()

    p.phase = "projects"
    from . import projects as projmod
    projmod.rebuild(con, cfg)

    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('last_scan',?)", (str(time.time()),))
    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('scan_seconds',?)",
                (str(round(time.time() - t0, 2)),))
    con.commit()
    try:
        con.execute("INSERT INTO files_fts(files_fts) VALUES('optimize')")
        con.commit()
    except Exception:
        pass

    p.phase = "done"
    p.finished = time.time()
    p.message = "新增 %d · 更新 %d · 移除 %d · 用时 %.1fs" % (
        p.added, p.updated, p.removed, p.finished - t0)
    return p.as_dict()


def _safe(job, cfg, p, bulk=frozenset()):
    try:
        return _process(job, cfg, bulk)
    except Exception:
        p.errors += 1
        return None


_SPLIT_RE = re.compile(r"[^\w一-鿿]+")


def _searchable_name(name: str, path: str) -> str:
    """文件名 + 所在目录名一起进索引——很多信息只在路径里。"""
    parts = [name, os.path.basename(os.path.dirname(path))]
    parts.append(" ".join(x for x in _SPLIT_RE.split(name) if x))
    return " ".join(parts)
