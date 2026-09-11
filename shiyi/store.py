"""SQLite 存储层：文件表 + FTS5 全文索引 + 项目表。

中文检索靠 FTS5 的 trigram 分词器——不需要 jieba，也不需要词典，
任意子串都能命中（三字及以上走索引，一到两字走 LIKE 回退）。
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path

from .config import DB_PATH, DATA_DIR

SCHEMA_VERSION = 4

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS files (
  id          INTEGER PRIMARY KEY,
  path        TEXT NOT NULL UNIQUE,
  parent      TEXT NOT NULL,
  name        TEXT NOT NULL,
  ext         TEXT NOT NULL,
  kind        TEXT NOT NULL,
  size        INTEGER NOT NULL,
  mtime       REAL NOT NULL,
  root        TEXT NOT NULL,
  project_id  INTEGER,
  text_status TEXT,
  text_len    INTEGER DEFAULT 0,
  fp          TEXT,               -- 正文指纹，用于查内容重复
  indexed_at  REAL
);
CREATE INDEX IF NOT EXISTS ix_files_mtime   ON files(mtime);
CREATE INDEX IF NOT EXISTS ix_files_kind    ON files(kind);
CREATE INDEX IF NOT EXISTS ix_files_project ON files(project_id);
CREATE INDEX IF NOT EXISTS ix_files_parent  ON files(parent);
CREATE INDEX IF NOT EXISTS ix_files_fp      ON files(fp);
CREATE INDEX IF NOT EXISTS ix_files_name    ON files(name);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts
  USING fts5(name, body, tokenize='trigram');

CREATE TABLE IF NOT EXISTS projects (
  id         INTEGER PRIMARY KEY,
  path       TEXT NOT NULL UNIQUE,
  name       TEXT NOT NULL,
  slug       TEXT,               -- 归一化名字，用于聚版本簇
  version    TEXT,
  kinds      TEXT,               -- 逗号分隔的技术标签
  file_count INTEGER DEFAULT 0,
  size       INTEGER DEFAULT 0,
  mtime      REAL DEFAULT 0,
  ctime      REAL DEFAULT 0,
  span       REAL DEFAULT 0,     -- 首末改动时间跨度，用来分辨「做出来的」和「解压出来的」
  is_git     INTEGER DEFAULT 0,
  git_branch TEXT,
  git_dirty  INTEGER DEFAULT 0,
  note       TEXT
);
CREATE INDEX IF NOT EXISTS ix_projects_slug ON projects(slug);

CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=30.0)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    cur = con.execute("SELECT v FROM meta WHERE k='schema'")
    row = cur.fetchone()
    if row is None:
        con.execute("INSERT INTO meta(k,v) VALUES('schema',?)", (str(SCHEMA_VERSION),))
        con.commit()
    elif int(row["v"]) != SCHEMA_VERSION:
        _migrate(con, int(row["v"]))
    return con


def _migrate(con: sqlite3.Connection, old: int) -> None:
    """结构变了就重建——索引本来就是可再生的，没有迁移的必要。"""
    con.executescript(
        "DROP TABLE IF EXISTS files;"
        "DROP TABLE IF EXISTS files_fts;"
        "DROP TABLE IF EXISTS projects;"
    )
    con.executescript(_SCHEMA)
    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('schema',?)", (str(SCHEMA_VERSION),))
    con.commit()


def get_meta(con, key: str, default=None):
    row = con.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return row["v"] if row else default


def set_meta(con, key: str, value) -> None:
    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (key, str(value)))


# ----------------------------------------------------------------- 查询
_FTS_SPECIAL = re.compile(r'["*():^-]')


def _fts_query(q: str) -> str:
    """把用户输入变成安全的 FTS5 查询：每个词做成带引号的短语，AND 连接。"""
    words = [w for w in re.split(r"\s+", q.strip()) if w]
    out = []
    for w in words:
        w = _FTS_SPECIAL.sub(" ", w).strip()
        if len(w) >= 3:
            out.append('"%s"' % w.replace('"', ""))
    return " AND ".join(out)


def _like_arg(s: str) -> str:
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


ORDERS = {"new": "f.mtime DESC", "old": "f.mtime ASC", "big": "f.size DESC"}
MARK_A, MARK_B = "\x02", "\x03"


# 空查询时默认只列这些：打开软件第一眼该看到「你最近在做什么」，
# 而不是被系统碰过的 .lnk 和 .gitignore。
RECENT_KINDS = ("doc", "slide", "sheet", "pdf")


def search(con, q: str, *, kind: str = "", root: str = "", project_id=None,
           limit: int = 60, offset: int = 0, order: str = "relevance",
           recent_work: bool = False) -> dict:
    """全文 + 文件名检索。返回 {total, hits, mode}。

    三条路：
      fts   —— 词长 >= 3，走 trigram 索引，毫秒级，带高亮片段；
      like  —— 一到两个字（中文里极常见：果蝇 / 支教 / 课表），
               trigram 组不出三元组，直接扫正文；
      list  —— 空查询，按时间列出。
    """
    q = (q or "").strip()
    where, args = [], []
    if kind:
        where.append("f.kind = ?")
        args.append(kind)
    if root:
        where.append("f.root = ?")
        args.append(root)
    if project_id:
        where.append("f.project_id = ?")
        args.append(project_id)
    cond = (" AND " + " AND ".join(where)) if where else ""

    if not q:
        base = "FROM files f WHERE 1"
        pre = []
        if recent_work and not kind:
            ph = ",".join("?" * len(RECENT_KINDS))
            base += " AND (f.kind IN (%s) OR f.ext IN ('.apk','.ipa'))" % ph
            base += " AND f.size > 4096"
            pre = list(RECENT_KINDS)
        sel = "f.*, '' AS snip, 0 AS score"
        osql = ORDERS.get(order, "f.mtime DESC")
        return _run(con, sel, base, cond, pre, args, osql, limit, offset, "list")

    fq = _fts_query(q)
    if fq:
        base = ("FROM files_fts JOIN files f ON f.id = files_fts.rowid "
                "WHERE files_fts MATCH ?")
        sel = ("f.*, snippet(files_fts, 1, '%s', '%s', ' … ', 44) AS snip, "
               "bm25(files_fts, 12.0, 1.0) AS score" % (MARK_A, MARK_B))
        osql = ORDERS.get(order, "score")
        res = _run(con, sel, base, cond, [fq], args, osql, limit, offset, "fts")
        if res["total"]:
            return res

    # 回退：直接扫正文。语料经过筛选后并不大，实测在毫秒到几十毫秒。
    like = _like_arg(q)
    base = ("FROM files_fts JOIN files f ON f.id = files_fts.rowid "
            "WHERE (files_fts.body LIKE ? ESCAPE '\\' OR files_fts.name LIKE ? ESCAPE '\\')")
    sel = "f.*, files_fts.body AS _body, 0 AS score"
    # 文件名里就有这个词的排前面，其次才按时间
    osql = ORDERS.get(order) or ("(f.name LIKE '%s' ESCAPE '\\') DESC, f.mtime DESC"
                                 % like.replace("'", "''"))
    res = _run(con, sel, base, cond, [like, like], args, osql, limit, offset, "like",
               count=False)
    for h in res["hits"]:
        h["snip"] = _make_snippet(h.pop("_body", "") or "", q)
    return res


def _run(con, sel, base, cond, pre, args, osql, limit, offset, mode,
         count: bool = True) -> dict:
    """count=False 时不再单独 COUNT(*)。

    LIKE 模式要把两百多兆正文过一遍，单独数一次总数等于把这活干两遍。
    多取一行就知道「还有没有更多」，够用了。
    """
    if count:
        total = con.execute("SELECT count(*) c " + base + cond, pre + args).fetchone()["c"]
        cap = limit
    else:
        total = None
        cap = limit + 1
    rows = con.execute(
        "SELECT " + sel + " " + base + cond + " ORDER BY " + osql + " LIMIT ? OFFSET ?",
        pre + args + [cap, offset],
    ).fetchall()
    more = False
    if total is None:
        more = len(rows) > limit
        rows = rows[:limit]
        total = offset + len(rows)
    return {"total": total, "more": more, "mode": mode,
            "hits": [dict(r) for r in rows]}


def _make_snippet(body: str, q: str, width: int = 46) -> str:
    """LIKE 模式没有 snippet()，自己截一段并打上高亮标记。"""
    if not body:
        return ""
    i = body.lower().find(q.lower())
    if i < 0:
        return body[:width * 2].replace("\n", " ")
    a = max(0, i - width // 2)
    b = min(len(body), i + len(q) + width)
    seg = body[a:b].replace("\n", " ")
    seg = (" … " if a else "") + seg + (" … " if b < len(body) else "")
    j = seg.lower().find(q.lower())
    if j >= 0:
        seg = seg[:j] + MARK_A + seg[j:j + len(q)] + MARK_B + seg[j + len(q):]
    return seg


def body_of(con, file_id: int) -> str:
    row = con.execute("SELECT body FROM files_fts WHERE rowid=?", (file_id,)).fetchone()
    return row["body"] if row else ""


def stats(con) -> dict:
    d = {}
    d["files"] = con.execute("SELECT count(*) c FROM files").fetchone()["c"]
    d["bytes"] = con.execute("SELECT coalesce(sum(size),0) s FROM files").fetchone()["s"]
    d["indexed_text"] = con.execute(
        "SELECT count(*) c FROM files WHERE text_len > 0").fetchone()["c"]
    d["projects"] = con.execute("SELECT count(*) c FROM projects").fetchone()["c"]
    d["by_kind"] = {r["kind"]: r["c"] for r in con.execute(
        "SELECT kind, count(*) c FROM files GROUP BY kind ORDER BY c DESC")}
    d["by_root"] = {r["root"]: r["c"] for r in con.execute(
        "SELECT root, count(*) c FROM files GROUP BY root ORDER BY c DESC")}
    try:
        d["db_bytes"] = os.path.getsize(DB_PATH)
    except OSError:
        d["db_bytes"] = 0
    d["last_scan"] = float(get_meta(con, "last_scan", 0) or 0)
    d["scan_seconds"] = float(get_meta(con, "scan_seconds", 0) or 0)
    return d


# ----------------------------------------------------------------- 维护
def health(con, deep: bool = False) -> dict:
    """索引体检：能不能用、有多大、有没有对不上的行。

    deep=True 才跑 SQLite 的完整性自检——那在 400MB 的库上要好几秒，
    不该在每次打开「关于」页时都做一遍。
    """
    out = {"ok": True, "problems": [], "deep": deep}
    if deep:
        try:
            r = con.execute("PRAGMA quick_check(1)").fetchone()
            if r and r[0] != "ok":
                out["ok"] = False
                out["problems"].append("数据库自检未通过：%s" % r[0])
        except sqlite3.DatabaseError as exc:
            out["ok"] = False
            out["problems"].append("数据库打不开：%s" % exc)
            return out

    n_files = con.execute("SELECT count(*) c FROM files").fetchone()["c"]
    n_fts = con.execute("SELECT count(*) c FROM files_fts").fetchone()["c"]
    out["files"] = n_files
    out["fts_rows"] = n_fts
    if n_files != n_fts:
        out["ok"] = False
        out["problems"].append("正文索引有 %d 行对不上文件表" % abs(n_files - n_fts))

    missing = con.execute(
        "SELECT count(*) c FROM files f"
        " WHERE NOT EXISTS (SELECT 1 FROM files_fts WHERE rowid = f.id)"
    ).fetchone()["c"]
    if missing:
        out["ok"] = False
        out["problems"].append("%d 个文件没有对应的索引行" % missing)

    try:
        page = con.execute("PRAGMA page_size").fetchone()[0]
        free = con.execute("PRAGMA freelist_count").fetchone()[0]
        out["reclaimable"] = page * free
    except sqlite3.DatabaseError:
        out["reclaimable"] = 0
    out["db_bytes"] = os.path.getsize(DB_PATH) if DB_PATH.exists() else 0
    return out


def vacuum(con) -> dict:
    """整理碎片。删过很多文件之后能收回不少空间。"""
    before = os.path.getsize(DB_PATH) if DB_PATH.exists() else 0
    con.execute("INSERT INTO files_fts(files_fts) VALUES('optimize')")
    con.commit()
    con.execute("VACUUM")
    con.commit()
    after = os.path.getsize(DB_PATH) if DB_PATH.exists() else 0
    return {"before": before, "after": after, "saved": max(0, before - after)}


def clear(con) -> None:
    """清空内容但保留结构，下一次扫描会重建。"""
    con.executescript(
        "DELETE FROM files;"
        "DELETE FROM files_fts;"
        "DELETE FROM projects;"
        "DELETE FROM meta WHERE k IN ('last_scan','scan_seconds');"
    )
    con.commit()
    con.execute("VACUUM")
    con.commit()
