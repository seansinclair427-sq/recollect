"""年鉴导出：生成一份独立的 HTML，可以直接打印成 PDF。

不引用任何外部资源，样式内联，断网、换电脑、发给别人都能打开。
"""
from __future__ import annotations

import datetime as dt
import html
import os
from pathlib import Path

from . import __version__, timeline

KIND_CN = {"doc": "文档", "slide": "幻灯", "sheet": "表格", "pdf": "PDF",
           "code": "代码", "image": "图片", "video": "视频", "audio": "音频",
           "archive": "压缩包", "app": "程序", "other": "其他"}


def _size(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return ("%d%s" % (n, u)) if u == "B" else ("%.1f%s" % (n, u))
        n /= 1024
    return str(n)


def _e(s) -> str:
    return html.escape(str(s or ""))


CSS = """
:root{--paper:#fbf9f5;--ink:#1b1815;--ink2:#4a423b;--muted:#8a7f74;
      --line:#e4ddd3;--seal:#b4451f;--surface:#fff}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
     font:14px/1.7 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:56px 40px 80px}
header{border-bottom:2px solid var(--ink);padding-bottom:20px;margin-bottom:34px;
       display:flex;align-items:flex-end;justify-content:space-between;gap:20px}
.year{font:600 62px/1 Georgia,"Songti SC","SimSun",serif;letter-spacing:.02em}
.sub{color:var(--muted);font-size:12.5px;text-align:right}
h2{font:600 15px/1.4 Georgia,"Songti SC",serif;letter-spacing:.08em;
   margin:38px 0 14px;padding-bottom:7px;border-bottom:1px solid var(--line)}
.stats{display:flex;flex-wrap:wrap;gap:10px}
.stat{flex:1 1 130px;background:var(--surface);border:1px solid var(--line);
      border-radius:9px;padding:15px 18px}
.stat b{display:block;font:600 26px/1.15 Georgia,"Songti SC",serif;
        font-variant-numeric:tabular-nums}
.stat span{font-size:11.5px;color:var(--muted)}
.chart{display:flex;align-items:flex-end;gap:5px;height:110px;
       border-bottom:1px solid var(--line);margin-top:6px}
.chart i{flex:1;background:#e8cfc2;border-radius:3px 3px 0 0;min-height:2px;display:block}
.chart i.hot{background:var(--seal)}
.xaxis{display:flex;gap:5px;font-size:10px;color:var(--muted);margin-top:5px}
.xaxis span{flex:1;text-align:center}
table{width:100%;border-collapse:collapse;font-size:12.5px}
td{padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
td.k{width:52px;color:var(--muted);font-size:11px;white-space:nowrap}
td.d{width:66px;color:var(--muted);text-align:right;white-space:nowrap;
     font-variant-numeric:tabular-nums}
td.s{width:64px;color:var(--muted);text-align:right;white-space:nowrap;
     font-variant-numeric:tabular-nums}
td.n{word-break:break-all}
.path{display:block;color:var(--muted);font-size:10.5px;margin-top:2px}
footer{margin-top:52px;padding-top:16px;border-top:1px solid var(--line);
       color:var(--muted);font-size:11.5px;display:flex;justify-content:space-between}
@media print{
  body{background:#fff}
  .wrap{padding:0}
  .stat,table{break-inside:avoid}
  h2{break-after:avoid}
}
"""


def year_html(con, year: int, *, owner: str = "") -> str:
    d = timeline.year_summary(con, year)
    acts = d["artifacts"]

    months = [0] * 12
    for a in acts:
        months[dt.datetime.fromtimestamp(a["mtime"]).month - 1] += 1
    peak = max(months) or 1

    rows = []
    for a in acts[:150]:
        when = dt.datetime.fromtimestamp(a["mtime"]).strftime("%m-%d")
        rows.append(
            "<tr><td class='k'>%s</td><td class='n'>%s<span class='path'>%s</span></td>"
            "<td class='s'>%s</td><td class='d'>%s</td></tr>"
            % (_e(KIND_CN.get(a["kind"], a["kind"])), _e(a["name"]),
               _e(os.path.dirname(a["path"])), _size(a["size"]), when))

    projrows = "".join(
        "<tr><td class='n'>%s<span class='path'>%s</span></td>"
        "<td class='d'>%d 次改动</td></tr>"
        % (_e(p["name"]), _e(p["path"]), p["hits"])
        for p in d["projects"][:15])

    kinds = "　".join("%s %d" % (KIND_CN.get(k, k), v)
                     for k, v in sorted(d["artifact_kinds"].items(),
                                        key=lambda kv: -kv[1]))

    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>%(year)d 年作品年鉴%(who)s</title>
<style>%(css)s</style></head><body><div class="wrap">

<header>
  <div><div class="year">%(year)d</div><div>作品年鉴%(who)s</div></div>
  <div class="sub">由「拾遗」生成于 %(now)s<br>共 %(files)s 个文件动过</div>
</header>

<div class="stats">
  <div class="stat"><b>%(nart)d</b><span>件成品</span></div>
  <div class="stat"><b>%(words)s</b><span>万字（成品正文）</span></div>
  <div class="stat"><b>%(nproj)d</b><span>个项目在动</span></div>
  <div class="stat"><b>%(busiest)s</b><span>最忙的月份</span></div>
  <div class="stat"><b>%(folders)s</b><span>个文件夹里有动静</span></div>
</div>

<h2>成品分布</h2>
<div class="chart">%(bars)s</div>
<div class="xaxis">%(xaxis)s</div>
<p style="color:var(--muted);font-size:12px;margin-top:12px">%(kinds)s</p>

<h2>这一年做出来的东西（%(nart)d 件，列出前 %(nrows)d）</h2>
<p style="color:var(--muted);font-size:11.5px;margin:-6px 0 10px">
不含下载目录与微信 / QQ / 网盘接收的文件。</p>
<table>%(rows)s</table>

<h2>最活跃的项目</h2>
<table>%(projrows)s</table>

<footer><span>拾遗 %(ver)s</span><span>只统计本机索引到的文件</span></footer>
</div></body></html>""" % {
        "year": year,
        "who": ("　·　" + _e(owner)) if owner else "",
        "css": CSS,
        "now": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "files": format(d["files"], ","),
        "nart": d["artifact_total"],
        "nrows": min(150, len(acts)),
        "words": "%.1f" % (d["words"] / 10000),
        "nproj": len(d["projects"]),
        "busiest": (d["busiest_month"] or "—")[5:] + " 月" if d["busiest_month"] else "—",
        "folders": format(d["folders"], ","),
        "bars": "".join(
            "<i class='%s' style='height:%.1f%%' title='%d月 %d 件'></i>"
            % ("hot" if c == peak else "", max(2, c / peak * 100), i + 1, c)
            for i, c in enumerate(months)),
        "xaxis": "".join("<span>%d</span>" % (i + 1) for i in range(12)),
        "kinds": _e(kinds),
        "rows": "".join(rows) or "<tr><td>这一年没有成品记录。</td></tr>",
        "projrows": projrows or "<tr><td>没有项目记录。</td></tr>",
        "ver": _e(__version__),
    }


def write_year(con, year: int, out_dir: str | None = None, owner: str = "") -> str:
    """生成年鉴文件，返回路径。"""
    target = Path(out_dir) if out_dir else (Path.home() / "Desktop")
    if not target.is_dir():
        target = Path.home()
    path = target / ("%d年作品年鉴.html" % year)
    path.write_text(year_html(con, year, owner=owner), encoding="utf-8")
    return str(path)
