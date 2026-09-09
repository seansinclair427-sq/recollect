"""命令行入口： python -m shiyi <命令>"""
from __future__ import annotations

import argparse
import os
import sys
import time

from . import __version__, report, store, scan, projects as projmod, timeline
from .config import Config, DATA_DIR, DB_PATH


def _hsize(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "%.1f%s" % (n, unit) if unit != "B" else "%dB" % n
        n /= 1024
    return str(n)


def _stdout_utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ----------------------------------------------------------------- 命令
def cmd_scan(args) -> int:
    cfg = Config.load()
    if args.root:
        cfg.roots = [os.path.abspath(r) for r in args.root]
    con = store.connect()
    p = scan.Progress()

    stop = False

    def ticker():
        while not stop:
            if p.phase == "enumerate":
                sys.stdout.write("\r  枚举中… %d 个文件" % p.seen)
            elif p.phase == "index":
                pct = (p.done / p.total * 100) if p.total else 100
                sys.stdout.write("\r  索引中… %d/%d (%.0f%%)  %-28s"
                                 % (p.done, p.total, pct, p.current[:28]))
            elif p.phase == "projects":
                sys.stdout.write("\r  识别项目…                                        ")
            sys.stdout.flush()
            time.sleep(0.25)

    import threading
    t = threading.Thread(target=ticker, daemon=True)
    print("扫描：" + " / ".join(cfg.roots))
    t.start()
    res = scan.scan(con, cfg, p, full=args.full)
    stop = True
    time.sleep(0.3)
    print("\r" + " " * 78 + "\r" + res["message"])
    s = store.stats(con)
    print("  文件 %d · 有正文 %d · 项目 %d · 索引 %s"
          % (s["files"], s["indexed_text"], s["projects"], _hsize(s["db_bytes"])))
    return 0


def cmd_search(args) -> int:
    con = store.connect()
    t0 = time.time()
    res = store.search(con, " ".join(args.query), kind=args.kind, limit=args.limit)
    ms = (time.time() - t0) * 1000
    print("%d 条结果  (%s, %.0fms)" % (res["total"], res["mode"], ms))
    for h in res["hits"]:
        print("\n  %s   %s  %s" % (h["name"], _hsize(h["size"]),
                                   time.strftime("%Y-%m-%d", time.localtime(h["mtime"]))))
        print("  %s" % h["path"])
        snip = (h.get("snip") or "").replace("\x02", "[").replace("\x03", "]")
        snip = " ".join(snip.split())
        if snip:
            print("  %s" % snip[:150])
    return 0


def cmd_projects(args) -> int:
    con = store.connect()
    rows = con.execute("SELECT * FROM projects ORDER BY mtime DESC LIMIT ?",
                       (args.limit,)).fetchall()
    for r in rows:
        print("%-34s %-22s %5d 文件 %9s  %s"
              % (r["name"][:32], (r["kinds"] or "")[:20], r["file_count"],
                 _hsize(r["size"]), time.strftime("%Y-%m-%d", time.localtime(r["mtime"]))))
    return 0


def cmd_clusters(args) -> int:
    con = store.connect()
    cl = projmod.clusters(con)[: args.limit]
    if not cl:
        print("没有发现版本堆积。")
        return 0
    waste = sum(c["waste"] for c in cl)
    print("%d 组版本堆积，冗余约 %s\n" % (len(cl), _hsize(waste)))
    for c in cl:
        print("● %s  (%d 份, 冗余 %s)" % (c["title"], c["count"], _hsize(c["waste"])))
        for m in c["members"][:6]:
            print("    %-9s %-9s %s" % (m["version"] or "-", _hsize(m["size"]), m["path"]))
        if len(c["members"]) > 6:
            print("    …… 还有 %d 份" % (len(c["members"]) - 6))
        print()
    return 0


def cmd_dups(args) -> int:
    con = store.connect()
    groups = projmod.duplicates(con, args.limit)
    if not groups:
        print("没有发现内容重复的文件。")
        return 0
    print("%d 组内容重复\n" % len(groups))
    for g in groups:
        print("● %s  %d 份  %s" % (g["label"], g["count"], _hsize(g["bytes"])))
        for m in g["members"]:
            print("    %s" % m["path"])
        print()
    return 0


def cmd_year(args) -> int:
    con = store.connect()
    y = args.year or time.localtime().tm_year
    d = timeline.year_summary(con, y)
    print("== %d 年 ==" % y)
    print("  动过 %d 个文件 · %s" % (d["files"], _hsize(d["bytes"])))
    print("  最忙的月份：%s（%d 个文件）" % (d["busiest_month"], d["busiest_count"]))
    print("  文档正文合计 %s 字" % format(d["words"], ","))
    print("  分类：" + "  ".join("%s %d" % (k, v) for k, v in list(d["by_kind"].items())[:8]))
    print("\n  作品（前 20）：")
    for a in d["artifacts"][:20]:
        print("    %-46s %9s  %s" % (a["name"][:44], _hsize(a["size"]),
                                     time.strftime("%m-%d", time.localtime(a["mtime"]))))
    print("\n  最活跃的项目：")
    for p in d["projects"][:10]:
        print("    %-34s %d 次改动" % (p["name"][:32], p["hits"]))
    return 0


def cmd_export(args) -> int:
    con = store.connect()
    y = args.year or time.localtime().tm_year
    path = report.write_year(con, y, args.out or None)
    print("年鉴已生成：%s" % path)
    print("用浏览器打开，Ctrl+P 就能存成 PDF。")
    return 0


def cmd_serve(args) -> int:
    from .server import serve
    cfg = Config.load()
    con = store.connect()
    empty = store.stats(con)["files"] == 0
    con.close()
    if empty:
        print("还没有索引。界面打开后会自动开始扫描，进度在左下角。")
    serve(args.port or cfg.port, open_browser=not args.no_browser)
    return 0


def cmd_where(args) -> int:
    print("数据目录：%s" % DATA_DIR)
    print("索引文件：%s" % DB_PATH)
    if DB_PATH.exists():
        print("索引大小：%s" % _hsize(os.path.getsize(DB_PATH)))
    print("扫描根目录：")
    for r in Config.load().roots:
        print("  %s %s" % ("✓" if os.path.isdir(r) else "✗", r))
    return 0


def cmd_reset(args) -> int:
    con = store.connect()
    con.close()
    for suffix in ("", "-wal", "-shm"):
        p = str(DB_PATH) + suffix
        if os.path.exists(p):
            os.remove(p)
    print("索引已清空。下次扫描会重建。")
    return 0


# ----------------------------------------------------------------- 入口
def main(argv=None) -> int:
    _stdout_utf8()
    ap = argparse.ArgumentParser(
        prog="shiyi", description="拾遗 —— 把散落在硬盘里的东西找回来")
    ap.add_argument("-V", "--version", action="version", version="拾遗 " + __version__)
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("scan", help="扫描并建立索引")
    s.add_argument("--full", action="store_true", help="忽略缓存，全部重读")
    s.add_argument("--root", action="append", help="临时指定扫描目录（可多次）")
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("search", help="检索")
    s.add_argument("query", nargs="+")
    s.add_argument("-k", "--kind", default="", help="限定类别 doc/slide/pdf/code/…")
    s.add_argument("-n", "--limit", type=int, default=12)
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("projects", help="列出识别到的项目")
    s.add_argument("-n", "--limit", type=int, default=40)
    s.set_defaults(fn=cmd_projects)

    s = sub.add_parser("clusters", help="版本堆积（同一个东西的多个副本）")
    s.add_argument("-n", "--limit", type=int, default=20)
    s.set_defaults(fn=cmd_clusters)

    s = sub.add_parser("dups", help="内容重复的文件")
    s.add_argument("-n", "--limit", type=int, default=30)
    s.set_defaults(fn=cmd_dups)

    s = sub.add_parser("year", help="年鉴")
    s.add_argument("year", nargs="?", type=int)
    s.set_defaults(fn=cmd_year)

    s = sub.add_parser("serve", help="启动网页界面")
    s.add_argument("-p", "--port", type=int)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("export", help="把年鉴导出成一个 HTML 文件")
    s.add_argument("year", nargs="?", type=int)
    s.add_argument("-o", "--out", help="输出目录，默认桌面")
    s.set_defaults(fn=cmd_export)

    sub.add_parser("where", help="索引存在哪").set_defaults(fn=cmd_where)
    sub.add_parser("reset", help="清空索引").set_defaults(fn=cmd_reset)

    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        return cmd_serve(argparse.Namespace(port=None, no_browser=False))
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
