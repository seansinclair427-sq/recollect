"""拾遗测试。只用标准库 unittest，python -m unittest 就能跑。"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shiyi import pdftext, projects, scan, store, textract, timeline   # noqa: E402
from shiyi.config import Config, kind_of, skip_content, looks_minified  # noqa: E402


# ═══════════════════════════════════════════════════════ 造样本
def make_docx(path, paras):
    body = "".join("<w:p><w:r><w:t>%s</w:t></w:r></w:p>" % p for p in paras)
    xml = ('<?xml version="1.0"?><w:document xmlns:w="x"><w:body>%s</w:body>'
           '</w:document>' % body)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)


def make_pptx(path, slides, notes=None, pad=0):
    """pad 用来把文件撑到「成品」的体积门槛（20KB）以上。"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        if pad:
            z.writestr("ppt/media/pad.bin",
                       bytes(range(256)) * (pad // 256 + 1),
                       compress_type=zipfile.ZIP_STORED)
        for i, texts in enumerate(slides, 1):
            runs = "".join("<a:p><a:r><a:t>%s</a:t></a:r></a:p>" % t for t in texts)
            z.writestr("ppt/slides/slide%d.xml" % i,
                       '<?xml version="1.0"?><p:sld xmlns:a="x" xmlns:p="y">'
                       "<p:cSld>%s</p:cSld></p:sld>" % runs)
            if notes and i <= len(notes):
                z.writestr("ppt/notesSlides/notesSlide%d.xml" % i,
                           '<?xml version="1.0"?><p:notes xmlns:a="x">'
                           "<a:p><a:r><a:t>%s</a:t></a:r></a:p></p:notes>" % notes[i - 1])


def make_xlsx(path, strings):
    si = "".join("<si><t>%s</t></si>" % s for s in strings)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/sharedStrings.xml",
                   '<?xml version="1.0"?><sst>%s</sst>' % si)
        z.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")


def make_pdf(path, lines):
    """造一个未压缩、WinAnsi 编码的小 PDF（走 latin-1 路径）。"""
    show = "\n".join("BT /F1 12 Tf 72 %d Td (%s) Tj ET" % (720 - 18 * i, t)
                     for i, t in enumerate(lines))
    stream = show.encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    out += b"trailer << /Root 1 0 R >>\n%%EOF"
    Path(path).write_bytes(bytes(out))


# ═══════════════════════════════════════════════════════ 分类 / 过滤
class TestConfig(unittest.TestCase):
    def test_kind_of(self):
        self.assertEqual(kind_of("a.PPTX"), "slide")
        self.assertEqual(kind_of("a.ino"), "code")
        self.assertEqual(kind_of("a.pdf"), "pdf")
        self.assertEqual(kind_of("a.apk"), "app")
        self.assertEqual(kind_of("noext"), "other")
        self.assertEqual(kind_of("Makefile"), "code")

    def test_skip_content(self):
        self.assertEqual(skip_content("x/app.min.js", 100, "code"), "generated")
        self.assertEqual(skip_content("x/package-lock.json", 100, "code"), "generated")
        self.assertEqual(skip_content("x/emoji-mart-main/src/a.js", 100, "code"), "vendor")
        self.assertEqual(skip_content("x/big.json", 999_999, "code"), "data")
        self.assertEqual(skip_content("x/a.py", 500, "code"), "")

    def test_looks_minified(self):
        self.assertTrue(looks_minified("x" * 5000))
        self.assertFalse(looks_minified("line\n" * 500))


# ═══════════════════════════════════════════════════════ 正文抽取
class TestExtract(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="shiyi-t-"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_docx(self):
        p = self.dir / "a.docx"
        make_docx(p, ["慧食安项目计划", "第二段落"])
        txt, st = textract.extract(str(p))
        self.assertEqual(st, "ok")
        self.assertIn("慧食安项目计划", txt)
        self.assertIn("第二段落", txt)

    def test_pptx_page_markers_and_notes(self):
        p = self.dir / "a.pptx"
        make_pptx(p, [["封面"], ["正文要点"]], notes=["讲稿一"])
        txt, st = textract.extract(str(p))
        self.assertEqual(st, "ok")
        self.assertIn("【第 1 页】", txt)
        self.assertIn("【第 2 页】", txt)
        self.assertIn("正文要点", txt)
        self.assertIn("讲稿一", txt)

    def test_xlsx(self):
        p = self.dir / "a.xlsx"
        make_xlsx(p, ["采购清单", "数量", "采购清单"])
        txt, st = textract.extract(str(p))
        self.assertEqual(st, "ok")
        self.assertIn("采购清单", txt)
        self.assertEqual(txt.count("采购清单"), 1, "重复单元格应当去重")

    def test_text_encodings(self):
        for enc in ("utf-8", "gb18030"):
            p = self.dir / ("e-%s.txt" % enc)
            p.write_bytes("中文编码测试".encode(enc))
            txt, st = textract.extract(str(p))
            self.assertEqual(st, "ok", enc)
            self.assertIn("中文编码测试", txt, enc)

    def test_corrupt_file_is_not_fatal(self):
        p = self.dir / "bad.docx"
        p.write_bytes(b"not a zip at all")
        txt, st = textract.extract(str(p))
        self.assertEqual(txt, "")
        self.assertTrue(st.startswith("error"), st)

    def test_binary_masquerading_as_text(self):
        p = self.dir / "x.txt"
        p.write_bytes(b"\x00\x01\x02" * 500)
        _txt, st = textract.extract(str(p))
        self.assertEqual(st, "binary")

    def test_unsupported_kind(self):
        p = self.dir / "a.png"
        p.write_bytes(b"\x89PNG")
        self.assertEqual(textract.extract(str(p))[1], "unsupported")


# ═══════════════════════════════════════════════════════ PDF
class TestPdf(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="shiyi-p-"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_simple_pdf(self):
        p = self.dir / "a.pdf"
        make_pdf(p, ["Hello Shiyi", "Second Line"])
        txt, st = pdftext.extract_ex(p.read_bytes())
        self.assertEqual(st, "ok", txt)
        self.assertIn("Hello Shiyi", txt)
        self.assertIn("Second Line", txt)

    def test_reading_order_top_down(self):
        """先画下面那行，也要按从上到下输出。"""
        p = self.dir / "b.pdf"
        stream = (b"BT /F1 12 Tf 72 100 Td (BOTTOM) Tj ET\n"
                  b"BT /F1 12 Tf 72 700 Td (TOP) Tj ET")
        _write_pdf_with_stream(p, stream)
        txt, _ = pdftext.extract_ex(p.read_bytes())
        self.assertLess(txt.index("TOP"), txt.index("BOTTOM"), txt)

    def test_same_line_left_to_right(self):
        p = self.dir / "c.pdf"
        stream = (b"BT /F1 12 Tf 300 500 Td (WORLD) Tj ET\n"
                  b"BT /F1 12 Tf 72 500 Td (HELLO) Tj ET")
        _write_pdf_with_stream(p, stream)
        txt, _ = pdftext.extract_ex(p.read_bytes())
        self.assertIn("HELLOWORLD", txt.replace(" ", ""))

    def test_not_a_pdf(self):
        self.assertEqual(pdftext.extract_ex(b"hello")[1], "notpdf")

    def test_cmap_bfchar(self):
        cm = pdftext._parse_cmap(b"beginbfchar <0003> <4E2D> <0004> <6587> endbfchar")
        self.assertEqual(cm[3], "中")
        self.assertEqual(cm[4], "文")

    def test_cmap_bfrange_incrementing(self):
        cm = pdftext._parse_cmap(b"beginbfrange <0010> <0012> <0041> endbfrange")
        self.assertEqual([cm[0x10], cm[0x11], cm[0x12]], ["A", "B", "C"])

    def test_cmap_bfrange_array(self):
        cm = pdftext._parse_cmap(
            b"beginbfrange <0020> <0021> [<4E2D> <6587>] endbfrange")
        self.assertEqual(cm[0x20], "中")
        self.assertEqual(cm[0x21], "文")

    def test_scrub_drops_control_glyphs(self):
        """子集字体常把码位映到控制符，那不是文字，早期版本靠阈值误杀了整篇。"""
        self.assertEqual(pdftext._scrub("中\x01文\x02"), "中文")

    def test_sanity_keeps_punctuation_heavy_chinese(self):
        s = "（1）孟德尔∶豌豆．F₁自交出现3∶1，" * 6
        self.assertEqual(pdftext._sanity(s), s.strip())


def _write_pdf_with_stream(path, stream):
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    out += b"trailer << /Root 1 0 R >>\n%%EOF"
    Path(path).write_bytes(bytes(out))


# ═══════════════════════════════════════════════════════ 版本归一化
class TestSlug(unittest.TestCase):
    def test_strips_versions(self):
        cases = {
            "OverWeather_v3": "overweather", "OverWeather_v3.2": "overweather",
            "huishian-v0.4.0-share": "huishian", "报名表(1)": "报名表",
            "企划书-修订版": "企划书", "企划书-已填写": "企划书",
            "方案 最终版": "方案", "笔记-备份": "笔记",
            "报告20260403": "报告",
        }
        for src, want in cases.items():
            self.assertEqual(projects.slugify(src), want, src)

    def test_keeps_meaningful_names(self):
        self.assertEqual(projects.slugify("慧食安"), "慧食安")
        self.assertEqual(projects.slugify("FocusLock"), "focuslock")

    def test_version_of(self):
        self.assertEqual(projects.version_of("huishian-v0.4.0-share"), "0.4.0")
        self.assertEqual(projects.version_of("OverWeather_v3"), "3")
        self.assertEqual(projects.version_of("企划书-修订版"), "修订")

    def test_version_sort_key(self):
        self.assertGreater(projects._vkey("0.5.0"), projects._vkey("0.4.0"))
        self.assertGreater(projects._vkey("10"), projects._vkey("9"))
        self.assertGreater(projects._vkey("1"), projects._vkey(""))

    def test_third_party_paths(self):
        self.assertTrue(projects._third_party(r"C:\x\PCL2\mods\a.jar"))
        self.assertTrue(projects._third_party(r"C:\x\emoji-mart-main\a.js"))
        self.assertFalse(projects._third_party(r"C:\x\人人都是CEO\a.docx"))


# ═══════════════════════════════════════════════════════ 端到端
class TestIndexEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="shiyi-e2e-"))
        self.root = self.tmp / "root"
        (self.root / "proj" / "node_modules").mkdir(parents=True)
        (self.root / "深夜项目").mkdir(parents=True)

        # 正文要够长：重复检测会跳过 200 字以下的碎文件，免得满屏噪声
        plan = ["慧食安面向住校生，把食堂菜单和饭卡消费合起来给出营养建议。"] * 8
        make_docx(self.root / "深夜项目" / "企划书.docx", plan)
        make_docx(self.root / "深夜项目" / "企划书-修订版.docx", plan)
        make_pptx(self.root / "深夜项目" / "路演.pptx", [["市长杯决赛"], ["果蝇实验"]])
        (self.root / "proj" / "package.json").write_text('{"name":"p"}', encoding="utf-8")
        (self.root / "proj" / "main.py").write_text("# 红绿灯控制\nprint(1)\n", encoding="utf-8")
        (self.root / "proj" / "node_modules" / "junk.js").write_text("x" * 100, encoding="utf-8")

        self.cfg = Config(roots=[str(self.root)])
        self.con = store.connect(self.tmp / "db.sqlite")

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _scan(self, **kw):
        return scan.scan(self.con, self.cfg, scan.Progress(), **kw)

    def test_scan_indexes_and_ignores(self):
        self._scan()
        names = {r["name"] for r in self.con.execute("SELECT name FROM files")}
        self.assertIn("企划书.docx", names)
        self.assertIn("main.py", names)
        self.assertNotIn("junk.js", names, "node_modules 必须被剪掉")

    def test_fts_search_chinese(self):
        self._scan()
        r = store.search(self.con, "慧食安")
        self.assertEqual(r["mode"], "fts")
        self.assertGreaterEqual(r["total"], 2)

    def test_two_char_query_falls_back_to_scan(self):
        """果蝇 / 支教 这类两字词组不出三元组，必须能靠扫描正文找到。"""
        self._scan()
        r = store.search(self.con, "果蝇")
        self.assertEqual(r["mode"], "like")
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["hits"][0]["name"], "路演.pptx")
        self.assertIn("果蝇", r["hits"][0]["snip"])

    def test_snippet_has_markers(self):
        self._scan()
        hit = store.search(self.con, "市长杯")["hits"][0]
        self.assertIn(store.MARK_A, hit["snip"])
        self.assertIn(store.MARK_B, hit["snip"])

    def test_search_is_injection_safe(self):
        self._scan()
        for q in ['"', "a AND b", "*", "x' OR 1=1 --", "NEAR(", "100%", "_"]:
            store.search(self.con, q)          # 不炸就算过

    def test_kind_filter(self):
        self._scan()
        r = store.search(self.con, "", kind="slide")
        self.assertTrue(all(h["kind"] == "slide" for h in r["hits"]))

    def test_incremental_rescan_is_a_noop(self):
        self._scan()
        res = self._scan()
        self.assertEqual(res["added"], 0)
        self.assertEqual(res["updated"], 0)

    def test_change_is_picked_up(self):
        self._scan()
        p = self.root / "proj" / "main.py"
        time.sleep(1.1)
        p.write_text("# 斑马线\nprint(2)\n", encoding="utf-8")
        res = self._scan()
        self.assertEqual(res["updated"], 1)
        self.assertEqual(store.search(self.con, "红绿灯")["total"], 0)
        self.assertEqual(store.search(self.con, "斑马线")["total"], 1)

    def test_deleted_file_leaves_index(self):
        self._scan()
        (self.root / "深夜项目" / "路演.pptx").unlink()
        res = self._scan()
        self.assertEqual(res["removed"], 1)
        self.assertEqual(store.search(self.con, "市长杯")["total"], 0)

    def test_no_orphan_fts_rows(self):
        self._scan()
        (self.root / "深夜项目" / "路演.pptx").unlink()
        self._scan()
        n_files = self.con.execute("SELECT count(*) c FROM files").fetchone()["c"]
        n_fts = self.con.execute("SELECT count(*) c FROM files_fts").fetchone()["c"]
        self.assertEqual(n_files, n_fts)

    def test_project_detection(self):
        self._scan()
        paths = {r["name"] for r in self.con.execute("SELECT name FROM projects")}
        self.assertIn("proj", paths)
        row = self.con.execute(
            "SELECT kinds FROM projects WHERE name='proj'").fetchone()
        self.assertIn("Node", row["kinds"])

    def test_files_get_project_id(self):
        self._scan()
        row = self.con.execute(
            "SELECT project_id FROM files WHERE name='main.py'").fetchone()
        self.assertIsNotNone(row["project_id"])

    def test_clusters_find_the_revision_pair(self):
        self._scan()
        cs = projects.clusters(self.con)
        slugs = {c["slug"] for c in cs}
        self.assertIn("企划书", slugs)

    def test_clusters_ignore_identical_names(self):
        """同名副本归重复检测管，不该报成版本堆积。"""
        (self.root / "b").mkdir()
        make_docx(self.root / "b" / "企划书.docx", ["别的内容"])
        self._scan()
        for c in projects.clusters(self.con):
            names = {m["name"] for m in c["members"]}
            versions = {m["version"] for m in c["members"] if m["version"]}
            self.assertTrue(len(names) > 1 or versions, c["title"])

    def test_duplicates_by_content(self):
        self._scan()
        groups = projects.duplicates(self.con)
        self.assertTrue(any(
            {"企划书.docx", "企划书-修订版.docx"} <= {m["name"] for m in g["members"]}
            for g in groups), "改名但内容一样的文件应当被抓到")

    def test_year_summary_runs(self):
        self._scan()
        y = timeline.year_summary(self.con, time.localtime().tm_year)
        self.assertGreaterEqual(y["files"], 4)
        self.assertIn("by_kind", y)

    def test_stats(self):
        self._scan()
        s = store.stats(self.con)
        self.assertGreater(s["files"], 0)
        self.assertGreater(s["indexed_text"], 0)


# ═══════════════════════════════════════════════════════ 服务端护栏
class TestServerGuards(unittest.TestCase):
    def test_static_path_traversal_is_blocked(self):
        from shiyi.server import WEB_DIR
        evil = (WEB_DIR / ".." / ".." / "shiyi" / "store.py").resolve()
        self.assertFalse(str(evil).startswith(str(WEB_DIR.resolve())))

    def test_token_is_long_enough(self):
        from shiyi.server import TOKEN
        self.assertGreaterEqual(len(TOKEN), 20)


class TestServerLive(unittest.TestCase):
    """真的把服务跑起来打一遍。护栏是这个工具最不能出错的地方——
    它有一个能用默认程序打开文件的接口，别的网页绝不能碰到它。"""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        from shiyi import server as srv

        cls.srv_mod = srv
        cls.tmp = Path(tempfile.mkdtemp(prefix="shiyi-srv-"))
        (cls.tmp / "root").mkdir()
        make_docx(cls.tmp / "root" / "备忘.docx", ["拾遗服务端测试文档"] * 6)

        cls.cfg = Config(roots=[str(cls.tmp / "root")])
        con = store.connect(cls.tmp / "db.sqlite")
        scan.scan(con, cls.cfg, scan.Progress())
        cls.indexed = con.execute("SELECT path FROM files LIMIT 1").fetchone()["path"]
        con.close()

        # 让 handler 用测试库和测试配置
        cls._orig_con, cls._orig_cfg = srv._con, srv._cfg
        srv._con = lambda: store.connect(cls.tmp / "db.sqlite")
        srv._cfg = lambda: cls.cfg

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.t = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.srv_mod._con, cls.srv_mod._cfg = cls._orig_con, cls._orig_cfg
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _req(self, path, data=None, headers=None):
        import urllib.error
        import urllib.request
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        body = None
        hdr = dict(headers or {})
        if data is not None:
            body = __import__("json").dumps(data).encode()
            hdr["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=hdr,
                                     method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8")

    def test_index_page_serves_and_injects_token(self):
        code, body = self._req("/")
        self.assertEqual(code, 200)
        self.assertIn(self.srv_mod.TOKEN, body)
        self.assertNotIn("__SHIYI_TOKEN__", body)

    def test_search_api(self):
        code, body = self._req("/api/search?q=%E6%8B%BE%E9%81%97")
        self.assertEqual(code, 200)
        self.assertGreaterEqual(__import__("json").loads(body)["total"], 1)

    def test_post_without_token_is_403(self):
        code, _ = self._req("/api/open", {"path": self.indexed})
        self.assertEqual(code, 403)

    def test_post_with_wrong_token_is_403(self):
        code, _ = self._req("/api/open", {"path": self.indexed},
                            {"X-Shiyi-Token": "nope"})
        self.assertEqual(code, 403)

    def test_cross_origin_is_403(self):
        code, _ = self._req("/api/open", {"path": self.indexed},
                            {"X-Shiyi-Token": self.srv_mod.TOKEN,
                             "Origin": "https://evil.example"})
        self.assertEqual(code, 403)

    def test_open_rejects_paths_outside_the_index(self):
        code, body = self._req("/api/open", {"path": r"C:\Windows\System32\calc.exe"},
                               {"X-Shiyi-Token": self.srv_mod.TOKEN})
        self.assertEqual(code, 403)
        self.assertIn("不在索引", body)

    def test_static_traversal_is_404(self):
        for p in ("/../shiyi/store.py", "/..%2fstore.py", "/%2e%2e/config.py"):
            code, _ = self._req(p)
            self.assertIn(code, (400, 403, 404), p)

    def test_unknown_endpoint_is_404(self):
        code, _ = self._req("/api/nope")
        self.assertEqual(code, 404)

    def test_bad_year_is_rejected(self):
        code, _ = self._req("/api/export-year", {"year": 99999},
                            {"X-Shiyi-Token": self.srv_mod.TOKEN})
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ═══════════════════════════════════════════════════════ 配置与外壳
class TestConfigClamp(unittest.TestCase):
    def test_clamp_pulls_values_into_range(self):
        c = Config(port=1, auto_scan_minutes=99999, max_text_bytes=1,
                   window_width=10, window_height=99999, theme="紫色")
        c.clamp()
        self.assertGreaterEqual(c.port, 1024)
        self.assertLessEqual(c.auto_scan_minutes, 1440)
        self.assertGreaterEqual(c.max_text_bytes, 10_000)
        self.assertGreaterEqual(c.window_width, 760)
        self.assertLessEqual(c.window_height, 2160)
        self.assertEqual(c.theme, "auto")

    def test_clamp_drops_blank_roots(self):
        c = Config(roots=[r"C:\keep", "", "   ", None])   # type: ignore[list-item]
        c.clamp()
        self.assertEqual(c.roots, [r"C:\keep"])

    def test_bad_config_file_falls_back_to_defaults(self):
        tmp = Path(tempfile.mkdtemp(prefix="shiyi-cfg-"))
        try:
            from shiyi import config as C
            old = C.CONFIG_PATH
            C.CONFIG_PATH = tmp / "config.json"
            C.CONFIG_PATH.write_text("{ this is not json", encoding="utf-8")
            c = Config.load()
            self.assertIsInstance(c.roots, list)
            self.assertEqual(c.port, 7331)
            C.CONFIG_PATH = old
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestIgnoreRules(unittest.TestCase):
    def test_sidecar_files_are_ignored(self):
        from shiyi.config import IGNORE_FILE_SUFFIXES
        for n in ("session.db-wal", "sns.db-shm", "a.material", "x.crdownload",
                  "y.part", "z.tmp"):
            self.assertTrue(n.lower().endswith(IGNORE_FILE_SUFFIXES), n)

    def test_real_files_are_not_ignored(self):
        from shiyi.config import IGNORE_FILE_SUFFIXES
        for n in ("报告.docx", "main.py", "笔记.md", "data.db"):
            self.assertFalse(n.lower().endswith(IGNORE_FILE_SUFFIXES), n)

    def test_chat_app_internals_are_pruned(self):
        from shiyi.config import IGNORE_DIRS
        for d in ("db_storage", "FileStorage", "CustomEmotion"):
            self.assertIn(d, IGNORE_DIRS)


class TestAppShell(unittest.TestCase):
    def test_runtime_roundtrip(self):
        from shiyi import app as A
        tmp = Path(tempfile.mkdtemp(prefix="shiyi-rt-"))
        try:
            old = A.RUNTIME_PATH
            A.RUNTIME_PATH = tmp / "runtime.json"
            A.write_runtime(7331, "tok123")
            d = A.read_runtime()
            self.assertEqual(d["port"], 7331)
            self.assertEqual(d["token"], "tok123")
            A.clear_runtime()
            self.assertEqual(A.read_runtime(), {})
            A.RUNTIME_PATH = old
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_read_runtime_survives_garbage(self):
        from shiyi import app as A
        tmp = Path(tempfile.mkdtemp(prefix="shiyi-rt2-"))
        try:
            old = A.RUNTIME_PATH
            A.RUNTIME_PATH = tmp / "runtime.json"
            A.RUNTIME_PATH.write_text("not json", encoding="utf-8")
            self.assertEqual(A.read_runtime(), {})
            A.RUNTIME_PATH = old
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_single_instance_second_acquire_fails(self):
        # 用独立名字，免得撞上真在跑的那一份
        from shiyi.app import SingleInstance
        name = r"Local\ShiyiTest_%d" % os.getpid()
        a, b = SingleInstance(name), SingleInstance(name)
        try:
            self.assertTrue(a.acquire())
            self.assertFalse(b.acquire())
            self.assertTrue(b.already_running)
        finally:
            b.release()
            a.release()


class TestPlatformBits(unittest.TestCase):
    def test_launch_command_is_quoted(self):
        from shiyi import winintegration as wi
        cmd = wi.launch_command()
        self.assertTrue(cmd.startswith('"'), cmd)
        self.assertIn(".exe", cmd.lower())

    def test_find_browser_returns_path_or_none(self):
        from shiyi.window import find_browser
        b = find_browser()
        self.assertTrue(b is None or Path(b).exists(), b)

    def test_resource_dir_has_web_assets(self):
        from shiyi import web_dir
        self.assertTrue((web_dir() / "index.html").is_file())
        self.assertTrue((web_dir() / "app.js").is_file())
        self.assertTrue((web_dir() / "icon.ico").is_file())


class TestMaintenance(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="shiyi-mt-"))
        (self.tmp / "root").mkdir()
        make_docx(self.tmp / "root" / "a.docx", ["维护测试内容"] * 8)
        self.cfg = Config(roots=[str(self.tmp / "root")])
        self.con = store.connect(self.tmp / "db.sqlite")
        scan.scan(self.con, self.cfg, scan.Progress())

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_health_shallow_is_ok(self):
        h = store.health(self.con)
        self.assertTrue(h["ok"])
        self.assertFalse(h["deep"])
        self.assertGreater(h["files"], 0)

    def test_health_deep_runs_integrity_check(self):
        h = store.health(self.con, deep=True)
        self.assertTrue(h["ok"], h["problems"])
        self.assertTrue(h["deep"])

    def test_clear_empties_everything(self):
        store.clear(self.con)
        self.assertEqual(store.stats(self.con)["files"], 0)
        self.assertEqual(store.search(self.con, "维护测试内容")["total"], 0)

    def test_rescan_after_clear_restores(self):
        store.clear(self.con)
        scan.scan(self.con, self.cfg, scan.Progress())
        self.assertGreater(store.search(self.con, "维护测试内容")["total"], 0)


class TestReport(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="shiyi-rp-"))
        (self.tmp / "root").mkdir()
        make_pptx(self.tmp / "root" / "路演.pptx", [["市长杯决赛"] * 40], pad=40_000)
        self.cfg = Config(roots=[str(self.tmp / "root")])
        self.con = store.connect(self.tmp / "db.sqlite")
        scan.scan(self.con, self.cfg, scan.Progress())

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_year_html_is_self_contained(self):
        from shiyi import report
        html = report.year_html(self.con, time.localtime().tm_year)
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("<style>", html)
        # 不能引用任何外部资源，换台电脑打开也要一样
        for bad in ("http://", "https://", "<script"):
            self.assertNotIn(bad, html.lower())

    def test_year_html_escapes_names(self):
        from shiyi import report
        # Windows 文件名不能带 < >，用 & 来验证转义走没走
        evil = self.tmp / "root" / "报告&注入.pptx"
        make_pptx(evil, [["注入测试"] * 30], pad=40_000)
        scan.scan(self.con, self.cfg, scan.Progress())
        html = report.year_html(self.con, time.localtime().tm_year)
        self.assertIn("报告&amp;注入", html)
        self.assertNotIn("报告&注入", html)

    def test_write_year_creates_file(self):
        from shiyi import report
        p = report.write_year(self.con, time.localtime().tm_year, str(self.tmp))
        self.assertTrue(Path(p).is_file())
        self.assertGreater(Path(p).stat().st_size, 500)


# ───────────────────────────────────────────────────────── 安装程序
@unittest.skipUnless(sys.platform == "win32", "安装程序只在 Windows 上存在")
class TestInstaller(unittest.TestCase):
    """只碰逻辑，不碰真的安装位置：注册表键换成测试专用的一条。"""

    def setUp(self):
        from shiyi import installer
        self.I = installer
        self.tmp = Path(tempfile.mkdtemp(prefix="shiyi-ins-"))
        self._key = installer.UNINSTALL_KEY
        installer.UNINSTALL_KEY = (
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
            r"\ShiyiTest_%d" % os.getpid())

    def tearDown(self):
        self.I.unregister()
        self.I.UNINSTALL_KEY = self._key
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_human_reads_like_a_person_wrote_it(self):
        self.assertEqual(self.I.human(0), "0 B")
        self.assertEqual(self.I.human(1024), "1 KB")
        self.assertEqual(self.I.human(24 * 1024 * 1024), "24 MB")
        self.assertEqual(self.I.human(3 * 1024 ** 3), "3.0 GB")

    def test_default_dir_is_per_user(self):
        d = self.I.default_dir()
        self.assertIn("Programs", str(d))
        self.assertTrue(str(d).endswith(self.I.APP_TITLE))
        # 不能落在需要管理员权限的地方
        self.assertNotIn("Program Files", str(d))

    def test_payload_zip_measures_uncompressed_size(self):
        src = self.tmp / "p.zip"
        body = b"x" * 5000
        with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("拾遗.exe", body)
            z.writestr("_internal/base.dll", body)
        # 压缩后远小于 10000，但要报的是解开以后的大小
        self.assertLess(src.stat().st_size, 10000)
        self.assertEqual(self.I.payload_bytes(src), 10000)

    def test_copy_payload_rebuilds_the_tree(self):
        src = self.tmp / "p.zip"
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("拾遗.exe", b"exe")
            z.writestr("_internal/sub/x.dll", b"dll")
        target = self.tmp / "out"
        seen = []
        self.I._copy_payload(src, target, lambda pct, note: seen.append(pct))
        self.assertTrue((target / "拾遗.exe").is_file())
        self.assertEqual((target / "_internal" / "sub" / "x.dll").read_bytes(),
                         b"dll")
        self.assertTrue(seen and 0.1 < seen[-1] <= 0.9)   # 进度在区间内

    def test_register_shows_up_in_add_remove_programs(self):
        import winreg
        target = self.tmp / "app"
        target.mkdir()
        self.I.register(target, 24 * 1024 * 1024)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            self.I.UNINSTALL_KEY) as k:
            def val(n):
                return winreg.QueryValueEx(k, n)[0]
            self.assertEqual(val("DisplayName"), self.I.DISPLAY_NAME)
            self.assertEqual(val("InstallLocation"), str(target))
            self.assertIn("--uninstall", val("UninstallString"))
            self.assertIn("--quiet", val("QuietUninstallString"))
            # 大小以 KB 记，不是字节 —— 写错了「应用和功能」里会显示 24 GB
            self.assertEqual(val("EstimatedSize"), 24 * 1024)
        self.I.unregister()
        with self.assertRaises(OSError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.I.UNINSTALL_KEY)

    def test_installed_dir_is_none_when_not_installed(self):
        self.assertIsNone(self.I.installed_dir())
        self.assertEqual(self.I.installed_version(), "")

    def test_installed_dir_ignores_a_stale_registry_entry(self):
        gone = self.tmp / "已经被手动删掉了"
        gone.mkdir()
        self.I.register(gone, 1)
        gone.rmdir()
        self.assertIsNone(self.I.installed_dir())     # 目录没了就不算装着

    def test_stop_running_is_fine_with_no_runtime_file(self):
        from shiyi import config
        old = config.DATA_DIR
        config.DATA_DIR = self.tmp / "nothing-here"
        try:
            self.assertTrue(self.I.stop_running(wait=0.1))
        finally:
            config.DATA_DIR = old

    def test_stop_running_shrugs_off_a_dead_pid(self):
        from shiyi import config
        old = config.DATA_DIR
        config.DATA_DIR = self.tmp
        (self.tmp / "runtime.json").write_text(
            '{"port": 1, "token": "x", "pid": 999999999}', "utf-8")
        try:
            self.assertTrue(self.I.stop_running(wait=0.5))
        finally:
            config.DATA_DIR = old

    def test_deferred_delete_declines_a_missing_folder(self):
        self.assertFalse(self.I.deferred_delete(self.tmp / "不存在"))
        self.assertFalse(self.I.deferred_delete(None))

    def test_writable_says_no_to_a_place_that_isnt_there(self):
        self.assertTrue(self.I.writable(self.tmp / "新建的"))
        # 找一个真没挂的盘符，别写死 Z: —— 万一 CI 上恰好映射了就假失败
        free = next((c for c in "ZYXWV" if not Path(c + ":/").exists()), None)
        if free is None:
            self.skipTest("这台机器盘符都占满了")
        self.assertFalse(self.I.writable(Path(free + ":/没有这个盘/x")))

    def test_silent_help_lists_every_flag_it_accepts(self):
        for flag in ("--silent", "--dir", "--no-desktop", "--no-menu",
                     "--autostart", "--launch"):
            self.assertIn(flag, self.I.SILENT_HELP)

    def test_install_refuses_a_place_it_cannot_write(self):
        free = next((c for c in "QZYXW" if not Path(c + ":/").exists()), None)
        if free is None:
            self.skipTest("这台机器盘符都占满了")
        with self.assertRaises(RuntimeError) as cm:
            self.I.do_install(Path(free + ":/没有这个盘/拾遗"), False, False,
                              False, lambda *_: None)
        # 要说人话，不是把 WinError 原样丢出来
        self.assertIn("写不进", str(cm.exception))

    def test_console_write_reports_whether_it_got_through(self):
        # 关键是它在任何情形下都不许抛，也不许挂着等人点对话框
        self.assertIsInstance(self.I.console_write("测试\n"), bool)
        self.assertIsInstance(self.I.console_write("测试\n", err=True), bool)


@unittest.skipUnless(sys.platform == "win32", "winui 只在 Windows 上有意义")
class TestWinUi(unittest.TestCase):
    def test_colour_helpers(self):
        from shiyi import winui
        # COLORREF 是 0x00BBGGRR，跟 CSS 的 0xRRGGBB 反着来
        self.assertEqual(winui._rgb(0xB4451F), 0x1F45B4)
        self.assertEqual(winui._argb(0xB4451F), 0xFFB4451F)
        self.assertEqual(winui.mix(0x000000, 0xFFFFFF, 0.5), 0x808080)
        self.assertEqual(winui.mix(0xB4451F, 0xB4451F, 0.7), 0xB4451F)

    def test_palette_matches_the_stylesheet(self):
        """朱砂和纸色必须跟 web/app.css 里是同一个值，不然两边会对不上。"""
        from shiyi import winui, web_dir
        css = (web_dir() / "app.css").read_text("utf-8")
        for token, value in (("--seal:", winui.SEAL), ("--paper:", winui.PAPER),
                             ("--ink:", winui.INK), ("--line:", winui.LINE)):
            want = "%s#%06x" % (token, value)
            self.assertIn(want, css.replace(" ", ""))
