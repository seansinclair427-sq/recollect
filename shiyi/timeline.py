"""时间线与年鉴。

把「一堆文件」翻译成「你做过什么」：按月的产出曲线、当年的作品清单、
最活跃的项目、以及一句话总结。
"""
from __future__ import annotations

import datetime as dt
import os
import time

# 进年鉴的东西：你做出来的成品。
# 刻意不收 .jar/.exe/.dll —— gradle-wrapper.jar 和 node.exe 不是你的作品；
# .apk 收，因为那是你自己编出来的（专注锁就是这么来的）。
ARTIFACT_SQL = """
  (
    (kind IN ('slide','doc','pdf','sheet','video')
     AND ext NOT IN ('.txt','.log','.json','.xml','.csv','.tsv','.ini','.cfg'))
    OR ext IN ('.apk','.ipa')
  )
  AND size > 20000
"""


def _month_key(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m")


def activity(con, months: int = 24) -> list:
    """近 N 个月，每月新增/改动了多少文件，分类别。"""
    cutoff = time.time() - months * 31 * 86400
    rows = con.execute(
        "SELECT mtime, kind FROM files WHERE mtime > ?", (cutoff,)
    ).fetchall()
    buckets: dict = {}
    for r in rows:
        k = _month_key(r["mtime"])
        b = buckets.setdefault(k, {"month": k, "total": 0, "kinds": {}})
        b["total"] += 1
        b["kinds"][r["kind"]] = b["kinds"].get(r["kind"], 0) + 1

    today = dt.date.today().replace(day=1)
    out = []
    for i in range(months - 1, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        key = "%04d-%02d" % (y, m)
        out.append(buckets.get(key, {"month": key, "total": 0, "kinds": {}}))
    return out


# 这些地方装的是「你收到的」，不是「你做的」：微信/QQ 的文件缓存、
# 网盘下载目录、浏览器下载。年鉴要回答「你做了什么」，把它们算进去
# 就变成了「你今年收了多少份文件」，那没有意义。
RECEIVED_SEGMENTS = {
    "xwechat_files", "wechat files", "wechatfiles", "tencent files",
    "tencentfiles", "qq files", "baidunetdiskdownload", "baidunetdisktmp",
    "downloads", "download", "迅雷下载", "接收的文件", "我的下载",
    # 原始素材不是成品：拍回来的片段、录屏、导出前的中间件
    "素材", "剪辑素材", "原素材", "raw", "footage", "录屏", "缓存", "cache",
}


def _is_received(path: str) -> bool:
    parts = [p.lower() for p in path.replace("/", "\\").split("\\")]
    return any(p in RECEIVED_SEGMENTS for p in parts)


def _artifacts(con, start: float, end: float, limit: int = 400) -> tuple:
    """一年里做出来的成品。返回 (列表, 去重后的真实总数)。

    同一份东西在三个文件夹里躺着只算一次；别人发来的、下载来的不算。
    """
    from .projects import _third_party

    rows = con.execute(
        "SELECT id, name, path, kind, ext, size, mtime, text_len, fp FROM files "
        "WHERE mtime>=? AND mtime<? AND " + ARTIFACT_SQL +
        " ORDER BY mtime DESC", (start, end)).fetchall()

    seen_fp: set = set()
    seen_name: set = set()
    out: list = []
    total = 0
    words = 0
    for r in rows:
        if _third_party(r["path"]) or _is_received(r["path"]):
            continue
        fp = r["fp"]
        if fp and fp in seen_fp:
            continue
        key = (r["name"].lower(), r["size"])
        if key in seen_name:
            continue
        if fp:
            seen_fp.add(fp)
        seen_name.add(key)
        total += 1
        words += r["text_len"] or 0
        if len(out) < limit:
            out.append(dict(r))
    return out, total, words


def year_summary(con, year: int) -> dict:
    """某一年的年鉴。"""
    start = dt.datetime(year, 1, 1).timestamp()
    end = dt.datetime(year + 1, 1, 1).timestamp()

    total = con.execute(
        "SELECT count(*) c, coalesce(sum(size),0) s FROM files WHERE mtime>=? AND mtime<?",
        (start, end)).fetchone()

    by_kind = {r["kind"]: r["c"] for r in con.execute(
        "SELECT kind, count(*) c FROM files WHERE mtime>=? AND mtime<? "
        "GROUP BY kind ORDER BY c DESC", (start, end))}

    artifacts, artifact_total, artifact_words = _artifacts(con, start, end)

    projects = [dict(r) for r in con.execute(
        "SELECT p.id, p.name, p.path, p.kinds, p.file_count, p.size, p.mtime,"
        " (SELECT count(*) FROM files f WHERE f.project_id=p.id AND f.mtime>=? AND f.mtime<?) hits"
        " FROM projects p WHERE p.mtime>=? AND p.mtime<?"
        " ORDER BY hits DESC LIMIT 24", (start, end, start, end))]

    busiest = con.execute(
        "SELECT strftime('%Y-%m', mtime, 'unixepoch', 'localtime') m, count(*) c"
        " FROM files WHERE mtime>=? AND mtime<? GROUP BY m ORDER BY c DESC LIMIT 1",
        (start, end)).fetchone()

    folders = con.execute(
        "SELECT count(DISTINCT parent) c FROM files WHERE mtime>=? AND mtime<?",
        (start, end)).fetchone()["c"]

    art_kinds: dict = {}
    for a in artifacts:
        art_kinds[a["kind"]] = art_kinds.get(a["kind"], 0) + 1

    return {
        "year": year,
        "files": total["c"],
        "bytes": total["s"],
        "folders": folders,
        "by_kind": by_kind,
        "artifact_kinds": art_kinds,
        "artifacts": artifacts,
        "artifact_total": artifact_total,
        "projects": projects,
        "busiest_month": busiest["m"] if busiest else None,
        "busiest_count": busiest["c"] if busiest else 0,
        # 只数成品里的正文。把收到的教材试卷也算上，就成了「你今年收了多少字」。
        "words": artifact_words,
    }


def years(con) -> list:
    rows = con.execute(
        "SELECT strftime('%Y', mtime, 'unixepoch', 'localtime') y, count(*) c"
        " FROM files GROUP BY y ORDER BY y DESC").fetchall()
    return [{"year": int(r["y"]), "count": r["c"]} for r in rows if r["y"] and r["y"].isdigit()]


def recent(con, days: int = 7, limit: int = 200) -> list:
    cutoff = time.time() - days * 86400
    return [dict(r) for r in con.execute(
        "SELECT f.id, f.name, f.path, f.kind, f.size, f.mtime, p.name pname"
        " FROM files f LEFT JOIN projects p ON p.id=f.project_id"
        " WHERE f.mtime > ? ORDER BY f.mtime DESC LIMIT ?", (cutoff, limit))]


def stale_projects(con, days: int = 120, limit: int = 40) -> list:
    """很久没碰、但曾经投入不少的项目——「你可能忘了它」。"""
    cutoff = time.time() - days * 86400
    return [dict(r) for r in con.execute(
        "SELECT id, name, path, kinds, file_count, size, mtime FROM projects"
        " WHERE mtime < ? AND file_count >= 8"
        " ORDER BY file_count DESC LIMIT ?", (cutoff, limit))]


def orphan_hotspots(con, limit: int = 20) -> list:
    """文件最多但不属于任何项目的目录——通常是该整理的地方。"""
    return [dict(r) for r in con.execute(
        "SELECT parent, count(*) c, sum(size) s, max(mtime) m FROM files"
        " WHERE project_id IS NULL GROUP BY parent"
        " HAVING c >= 5 ORDER BY c DESC LIMIT ?", (limit,))]
