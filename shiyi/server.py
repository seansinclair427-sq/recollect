"""本地 HTTP 服务：JSON API + 网页界面。

只监听 127.0.0.1。凡是有副作用的接口（扫描、打开文件、改设置、退出）
都要带启动时生成的一次性 token —— 否则你浏览器里随便一个网页都能对
localhost:7331 发请求，把你的文件打开一遍。
"""
from __future__ import annotations

import csv
import io
import json
import logging
import mimetypes
import os
import secrets
import subprocess
import threading
import time
import urllib.parse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, report, store, scan, projects as projmod, timeline, web_dir
from .config import Config, DATA_DIR, DB_PATH

WEB_DIR = web_dir()
TOKEN = secrets.token_urlsafe(18)
log = logging.getLogger("shiyi.server")

# 由 app.Application 注入；命令行 `shiyi serve` 时保持 None
APP = None

_local = threading.local()
_scan_lock = threading.Lock()
_scan_progress = scan.Progress()
_scan_thread: threading.Thread | None = None


def _con():
    if getattr(_local, "con", None) is None:
        _local.con = store.connect()
    return _local.con


def _cfg() -> Config:
    return Config.load()


def _progress():
    return APP.scanner.progress if (APP and APP.scanner) else _scan_progress


def _scanning() -> bool:
    if APP and APP.scanner:
        return APP.scanner.running
    return bool(_scan_thread and _scan_thread.is_alive())


# ----------------------------------------------------------------- 处理器
class Handler(BaseHTTPRequestHandler):
    server_version = "Shiyi/" + __version__
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- 基础
    def log_message(self, fmt, *args):
        pass                                    # 别把终端刷满

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _err(self, code: int, msg: str):
        self._json({"error": msg}, code)

    def _guard(self) -> bool:
        """副作用接口的护栏：token + 同源检查。"""
        tok = self.headers.get("X-Shiyi-Token") or self._query().get("t", [""])[0]
        if not secrets.compare_digest(tok or "", TOKEN):
            self._err(403, "bad token")
            return False
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
            self._err(403, "bad origin")
            return False
        return True

    def _query(self) -> dict:
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def _arg(self, key: str, default=""):
        return self._query().get(key, [default])[0]

    def _int(self, key: str, default: int) -> int:
        try:
            return int(self._arg(key, str(default)))
        except ValueError:
            return default

    def _drain(self) -> dict:
        """必须先把请求体读干净，再决定回不回绝。

        HTTP/1.1 是长连接：403 的时候直接回复、把 body 留在 socket 里，
        下一个请求就会读到上一个请求的残渣，客户端收到 WinError 10053。
        """
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = b""
        if 0 < n <= 1_000_000:
            raw = self.rfile.read(n)
        elif n > 1_000_000:
            remaining = n
            while remaining > 0:                # 太大就丢弃，但也要读完
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            return {}
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    # ------------------------------------------------------------- 路由
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path.startswith("/api/"):
                return self._api_get(path[5:])
            return self._static(path)
        except BrokenPipeError:
            pass
        except Exception as exc:
            log.exception("GET %s 出错", path)
            self._err(500, "%s: %s" % (type(exc).__name__, exc))

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._drain()                    # 先读干净，再谈别的
        try:
            if not path.startswith("/api/"):
                return self._err(404, "not found")
            return self._api_post(path[5:], body)
        except Exception as exc:
            log.exception("POST %s 出错", path)
            self._err(500, "%s: %s" % (type(exc).__name__, exc))

    # ------------------------------------------------------------- 静态
    def _static(self, path: str):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            return self._err(404, "not found")
        data = target.read_bytes()
        if target.name == "index.html":
            data = data.replace(b"__SHIYI_TOKEN__", TOKEN.encode())
            data = data.replace(b"__SHIYI_VERSION__", __version__.encode())
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or "javascript" in ctype or "json" in ctype:
            ctype += "; charset=utf-8"
        extra = {"Cache-Control": "public, max-age=3600"} if rel.startswith("icon") else None
        self._send(200, data, ctype, extra)

    # ------------------------------------------------------------- GET API
    def _api_get(self, ep: str):
        con = _con()

        if ep == "stats":
            s = store.stats(con)
            c = _cfg()
            s["version"] = __version__
            s["roots"] = c.roots
            s["theme"] = c.theme
            s["years"] = timeline.years(con)
            s["scanning"] = _scanning()
            s["has_shell"] = APP is not None
            return self._json(s)

        if ep == "search":
            t0 = time.time()
            res = store.search(
                con, self._arg("q"),
                kind=self._arg("kind"), root=self._arg("root"),
                project_id=self._int("project", 0) or None,
                limit=min(200, self._int("limit", 40)),
                offset=self._int("offset", 0),
                order=self._arg("order", "relevance"),
                recent_work=self._arg("recent") == "1",
            )
            res["ms"] = round((time.time() - t0) * 1000, 1)
            return self._json(res)

        if ep.startswith("file/"):
            return self._file_detail(con, ep.split("/", 1)[1])

        if ep == "projects":
            rows = con.execute("SELECT * FROM projects ORDER BY mtime DESC").fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["unpacked"] = projmod.looks_unpacked(d["file_count"], d["span"] or 0)
                d["third_party"] = projmod.is_third_party(d["path"])
                out.append(d)
            # 你亲手做的排前面，解压/安装出来的沉底
            out.sort(key=lambda d: (d["unpacked"] or d["third_party"], -d["mtime"]))
            return self._json({"projects": out})

        if ep == "clusters":
            return self._json({"clusters": projmod.clusters(con)[: self._int("limit", 80)]})

        if ep == "duplicates":
            return self._json({"groups": projmod.duplicates(con, self._int("limit", 120))})

        if ep == "timeline":
            return self._json({
                "activity": timeline.activity(con, self._int("months", 24)),
                "recent": timeline.recent(con, self._int("days", 14), 60),
                "stale": timeline.stale_projects(con),
                "orphans": timeline.orphan_hotspots(con),
            })

        if ep.startswith("year/"):
            return self._json(timeline.year_summary(con, int(ep.split("/", 1)[1])))

        if ep == "scan/status":
            d = _progress().as_dict()
            d["running"] = _scanning()
            return self._json(d)

        if ep == "settings":
            return self._json(self._settings_payload())

        if ep == "about":
            return self._json(self._about_payload(con))

        if ep == "log":
            from .logsetup import tail
            return self._json({"text": tail(self._int("lines", 300))})

        return self._err(404, "unknown endpoint")

    def _file_detail(self, con, raw_id: str):
        try:
            fid = int(raw_id)
        except ValueError:
            return self._err(400, "bad id")
        row = con.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
        if not row:
            return self._err(404, "no such file")
        d = dict(row)
        d["body"] = store.body_of(con, fid)[:60000]
        d["exists"] = os.path.exists(d["path"])
        if d["project_id"]:
            pr = con.execute("SELECT name, path FROM projects WHERE id=?",
                             (d["project_id"],)).fetchone()
            d["project"] = dict(pr) if pr else None
        if d["fp"]:
            d["copies"] = [dict(r) for r in con.execute(
                "SELECT id, path, name, mtime FROM files WHERE fp=? AND id<>? LIMIT 10",
                (d["fp"], fid))]
        return self._json(d)

    def _settings_payload(self) -> dict:
        c = _cfg()
        d = asdict(c)
        from . import winintegration as wi
        d["autostart"] = wi.autostart_enabled()
        d["platform_supported"] = wi.supported()
        d["data_dir"] = str(DATA_DIR)
        return d

    def _about_payload(self, con) -> dict:
        import platform
        import sqlite3 as sq
        import sys
        from .logsetup import LOG_PATH
        from .window import find_browser
        from . import winintegration as wi

        h = store.health(con)
        browser = find_browser()
        return {
            "version": __version__,
            "python": sys.version.split()[0],
            "sqlite": sq.sqlite_version,
            "platform": platform.platform(),
            "frozen": bool(getattr(sys, "frozen", False)),
            "data_dir": str(DATA_DIR),
            "db_path": str(DB_PATH),
            "log_path": str(LOG_PATH),
            "browser": Path(browser).name if browser else None,
            "autostart": wi.autostart_enabled(),
            "health": h,
            "has_shell": APP is not None,
        }

    # ------------------------------------------------------------- POST API
    def _api_post(self, ep: str, body: dict):
        if not self._guard():
            return

        if ep == "scan":
            return self._start_scan(bool(body.get("full")))

        if ep == "open":
            return self._open(body.get("path", ""), body.get("reveal", False))

        if ep == "settings":
            return self._save_settings(body)

        if ep == "export-year":
            return self._export_year(body)

        if ep == "export-search":
            return self._export_search(body)

        if ep == "maintenance":
            return self._maintenance(body.get("action", ""))

        if ep == "autostart":
            from . import winintegration as wi
            ok = wi.set_autostart(bool(body.get("enable")))
            return self._json({"ok": ok, "autostart": wi.autostart_enabled()})

        if ep == "install":
            from . import winintegration as wi
            return self._json(wi.install(
                desktop=body.get("desktop", True),
                start_menu=body.get("start_menu", True),
                autostart=body.get("autostart", False)))

        if ep == "uninstall":
            from . import winintegration as wi
            return self._json(wi.uninstall(remove_index=bool(body.get("remove_index"))))

        if ep == "quit":
            if APP is None:
                return self._err(400, "命令行模式下请用 Ctrl+C 退出")
            threading.Timer(0.3, APP.shutdown).start()
            return self._json({"ok": True})

        return self._err(404, "unknown endpoint")

    # ------------------------------------------------------------- 动作
    def _start_scan(self, full: bool):
        global _scan_thread
        if _scanning():
            return self._json({"ok": False, "running": True})
        if APP and APP.scanner and not full:
            APP.scanner.trigger()
            return self._json({"ok": True, "running": True})

        with _scan_lock:
            def work():
                con = store.connect()
                try:
                    scan.scan(con, _cfg(), _progress(), full=full)
                except Exception as exc:
                    p = _progress()
                    p.phase = "error"
                    p.message = "%s: %s" % (type(exc).__name__, exc)
                    p.finished = time.time()
                    log.exception("扫描出错")
                finally:
                    con.close()

            _scan_thread = threading.Thread(target=work, daemon=True, name="shiyi-scan")
            _scan_thread.start()
        return self._json({"ok": True, "running": True})

    def _save_settings(self, body: dict):
        c = _cfg()
        roots = body.get("roots")
        if isinstance(roots, list):
            good = [r for r in roots if isinstance(r, str) and os.path.isdir(r)]
            bad = [r for r in roots if isinstance(r, str) and not os.path.isdir(r)]
            if not good:
                return self._err(400, "没有一个可用的目录")
            c.roots = good
            if bad:
                log.warning("忽略不存在的目录：%s", bad)
        if isinstance(body.get("extra_ignores"), list):
            c.extra_ignores = [str(x).strip() for x in body["extra_ignores"]
                               if str(x).strip()][:200]
        for key in ("index_content", "scan_on_start", "minimize_to_tray",
                    "open_window_on_start"):
            if isinstance(body.get(key), bool):
                setattr(c, key, body[key])
        for key in ("port", "auto_scan_minutes", "max_text_bytes",
                    "window_width", "window_height"):
            if isinstance(body.get(key), (int, float)):
                setattr(c, key, int(body[key]))
        if body.get("theme") in ("auto", "light", "dark"):
            c.theme = body["theme"]
        c.first_run_done = True
        c.clamp().save()
        log.info("设置已保存")
        return self._json({"ok": True, "settings": self._settings_payload(),
                           "restart_needed": bool(
                               isinstance(body.get("port"), int)
                               and body["port"] != (APP.port if APP else c.port))})

    def _export_year(self, body: dict):
        try:
            year = int(body.get("year") or 0)
        except (TypeError, ValueError):
            return self._err(400, "bad year")
        if not 1990 <= year <= 2100:
            return self._err(400, "bad year")
        try:
            path = report.write_year(_con(), year)
        except OSError as exc:
            return self._err(500, str(exc))
        return self._json({"ok": True, "path": path})

    def _export_search(self, body: dict):
        """把当前的检索结果导成 CSV 或 Markdown，放到桌面。"""
        q = str(body.get("q", ""))
        fmt = body.get("format", "csv")
        if fmt not in ("csv", "md"):
            return self._err(400, "格式只支持 csv 或 md")
        res = store.search(_con(), q, kind=str(body.get("kind", "")),
                           limit=min(2000, int(body.get("limit") or 500)),
                           order=str(body.get("order", "relevance")))
        hits = res["hits"]
        stamp = time.strftime("%Y%m%d-%H%M")
        safe = "".join(ch for ch in (q or "全部") if ch not in r'\/:*?"<>|')[:40]
        target = _desktop() / ("拾遗-%s-%s.%s" % (safe, stamp, fmt))
        try:
            if fmt == "csv":
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(["名称", "类别", "大小", "修改时间", "路径", "摘要"])
                for h in hits:
                    w.writerow([h["name"], h["kind"], h["size"],
                                time.strftime("%Y-%m-%d %H:%M",
                                              time.localtime(h["mtime"])),
                                h["path"], _plain(h.get("snip"))])
                # Excel 认 BOM 才不会把中文显示成乱码
                target.write_text("﻿" + buf.getvalue(), encoding="utf-8")
            else:
                lines = ["# 拾遗检索结果：%s" % (q or "（全部）"), "",
                         "共 %d 条，导出于 %s" % (len(hits), time.strftime("%Y-%m-%d %H:%M")), ""]
                for h in hits:
                    lines.append("- **%s** — `%s`" % (h["name"], h["path"]))
                    snip = _plain(h.get("snip"))
                    if snip:
                        lines.append("  > %s" % snip)
                target.write_text("\n".join(lines), encoding="utf-8")
        except OSError as exc:
            return self._err(500, str(exc))
        return self._json({"ok": True, "path": str(target), "count": len(hits)})

    def _maintenance(self, action: str):
        con = _con()
        if action == "check":
            return self._json({"ok": True, "health": store.health(con, deep=True)})
        if action == "vacuum":
            if _scanning():
                return self._err(409, "正在扫描，稍后再试")
            return self._json({"ok": True, "result": store.vacuum(con)})
        if action == "rebuild":
            if _scanning():
                return self._err(409, "正在扫描，稍后再试")
            store.clear(con)
            return self._start_scan(True)
        if action == "reset":
            if _scanning():
                return self._err(409, "正在扫描，稍后再试")
            store.clear(con)
            return self._json({"ok": True, "cleared": True})
        return self._err(400, "未知的维护动作")

    def _open(self, path: str, reveal: bool):
        """在资源管理器里定位，或用默认程序打开。只允许已入库的路径。"""
        if not path:
            return self._err(400, "no path")
        con = _con()
        row = con.execute(
            "SELECT 1 FROM files WHERE path=? UNION SELECT 1 FROM projects WHERE path=?",
            (path, path)).fetchone()
        if not row and not _is_exported(path):
            return self._err(403, "路径不在索引内")
        if not os.path.exists(path):
            return self._err(404, "文件已不存在")
        try:
            if reveal or os.path.isdir(path):
                subprocess.Popen(["explorer", "/select," + os.path.normpath(path)]
                                 if not os.path.isdir(path)
                                 else ["explorer", os.path.normpath(path)])
            else:
                os.startfile(path)              # noqa: S606  用户在自己机器上点的
        except Exception as exc:
            log.exception("打开 %s 失败", path)
            return self._err(500, str(exc))
        return self._json({"ok": True})


def _plain(snip) -> str:
    return (snip or "").replace(store.MARK_A, "").replace(store.MARK_B, "").strip()


def _desktop() -> Path:
    p = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
    return p if p.is_dir() else Path.home()


def _is_exported(path: str) -> bool:
    """刚导出的年鉴 / 检索结果还没进索引，也要允许打开。"""
    base = os.path.basename(path)
    if not os.path.isfile(path):
        return False
    return base.endswith("年作品年鉴.html") or base.startswith("拾遗-")


# ----------------------------------------------------------------- 启动
def bind(port: int = 7331, tries: int = 12):
    """占端口。被占了就往后挪，双击启动的人不该看见 traceback。"""
    last = None
    for p in range(port, port + tries):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            httpd.daemon_threads = True
            return httpd, p
        except OSError as exc:
            last = exc
            continue
    raise SystemExit("端口 %d–%d 都被占用了：%s" % (port, port + tries - 1, last))


def serve(port: int = 7331, open_browser: bool = True) -> None:
    """命令行模式：不带托盘，Ctrl+C 停止。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    httpd, port = bind(port)
    url = "http://127.0.0.1:%d/" % port
    print("拾遗已启动  ->  " + url)
    print("（只监听本机；关掉这个窗口即停止）")
    if open_browser:
        from .window import AppWindow
        threading.Timer(0.6, lambda: AppWindow(DATA_DIR / "window").open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n再见。")
    finally:
        httpd.server_close()
