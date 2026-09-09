"""项目识别、版本簇归并、重复检测。

三件事：
  1. 从一堆散落的目录里认出「哪些是一个项目」；
  2. 把 OverWeather_v3 / v3.2 / v4 这种同源副本归成一簇，指出最新的那个；
  3. 用正文指纹找出改了名字但内容一样的文件。
"""
from __future__ import annotations

import os
import re
import time

from .config import Config, is_third_party, not_my_work

# 目录里出现这些文件 => 是个代码项目
MARKERS = {
    "package.json": "Node", "pnpm-lock.yaml": "Node", "yarn.lock": "Node",
    "requirements.txt": "Python", "pyproject.toml": "Python", "setup.py": "Python",
    "Pipfile": "Python", "environment.yml": "Python",
    "Cargo.toml": "Rust", "go.mod": "Go", "pom.xml": "Java",
    "build.gradle": "Gradle", "build.gradle.kts": "Gradle", "settings.gradle": "Gradle",
    "CMakeLists.txt": "C/C++", "Makefile": "Make", "makefile": "Make",
    "composer.json": "PHP", "Gemfile": "Ruby", "pubspec.yaml": "Flutter",
    "AndroidManifest.xml": "Android", "Info.plist": "Apple",
    "index.html": "Web", "manifest.json": "Web", "vite.config.js": "Web",
    "tsconfig.json": "TypeScript", "Dockerfile": "Docker",
}
MARKER_EXT = {".sln": "C#", ".csproj": "C#", ".ino": "Arduino", ".pde": "Arduino",
              ".xcodeproj": "Apple", ".iml": "Java"}

LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".java": "Java", ".kt": "Kotlin", ".c": "C", ".h": "C",
    ".cpp": "C++", ".cs": "C#", ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
    ".php": "PHP", ".swift": "Swift", ".dart": "Dart", ".lua": "Lua",
    ".html": "HTML", ".css": "CSS", ".vue": "Vue", ".ino": "Arduino",
    ".sh": "Shell", ".ps1": "PowerShell", ".bat": "Batch", ".sql": "SQL",
}


# ----------------------------------------------------------------- 版本归一化
_VER_PAT = [
    r"[ _\-.]*v\d+(?:[._]\d+)*",              # v3  v0.4.0  _v3.2
    r"[ _\-.]*\d+\.\d+(?:\.\d+)*",            # 0.4.0
    r"[ _\-]*\(\d+\)",                        # (1) (2)
    r"[ _\-]*\d{8}",                          # 20260403
    r"[ _\-]*\d{4}[-_]\d{2}[-_]\d{2}",        # 2026-04-03
    r"[ _\-]*(?:copy|副本|备份|bak|backup|old|new|final|latest|test|tmp|temp)",
    r"[ _\-]*(?:最终版?|最新版?|修订版?|完整版|精简版|分享版|发布版|定稿|终稿|草稿)",
    r"[ _\-]*(?:已填写|待填|未完成|已完成|已修改|重制版?|改)",
    r"[ _\-]*(?:share|release|dist|build|setup|x64|x86|win|windows)",
]
_VER_RE = re.compile("(?:" + "|".join(_VER_PAT) + ")+$", re.I)
_VER_GRAB = re.compile(r"v?(\d+(?:[._]\d+)*)", re.I)


def slugify(name: str) -> str:
    """去掉版本尾巴，得到「同一件东西」的稳定名字。"""
    s = name.strip()
    s = re.sub(r"\.(zip|rar|7z|tar|gz)$", "", s, flags=re.I)
    prev = None
    while prev != s:
        prev = s
        s = _VER_RE.sub("", s).strip(" _-.")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s or name.strip().lower()


def version_of(name: str) -> str:
    tail = name[len(slugify(name)):] if name.lower().startswith(slugify(name)) else name
    m = _VER_GRAB.search(tail) or _VER_GRAB.search(name)
    if m:
        return m.group(1).replace("_", ".")
    for kw in ("最终", "最新", "修订", "完整", "定稿", "终稿", "final", "latest", "release"):
        if kw in name.lower():
            return kw
    return ""


def _vkey(v: str):
    """版本号排序键；非数字版本排在数字之后。"""
    parts = re.findall(r"\d+", v)
    if parts:
        return (1, [int(x) for x in parts])
    return (0, [])


# ----------------------------------------------------------------- 识别
def _git_info(path: str) -> tuple:
    head = os.path.join(path, ".git", "HEAD")
    if not os.path.isfile(head):
        return None, 0.0
    try:
        with open(head, "r", encoding="utf-8", errors="ignore") as fh:
            ref = fh.read().strip()
        branch = ref.split("/")[-1] if ref.startswith("ref:") else ref[:8]
    except OSError:
        return None, 0.0
    last = 0.0
    log = os.path.join(path, ".git", "logs", "HEAD")
    try:
        with open(log, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            back = min(4096, fh.tell())
            fh.seek(-back, os.SEEK_END)
            tail = fh.read().decode("utf-8", "ignore").strip().splitlines()
        if tail:
            m = re.search(r"\s(\d{9,11})\s[+-]\d{4}", tail[-1])
            if m:
                last = float(m.group(1))
    except OSError:
        pass
    return branch, last


def detect(con, cfg: Config) -> list:
    """返回项目字典列表。"""
    dirs = {r["parent"] for r in con.execute("SELECT DISTINCT parent FROM files")}
    roots = {os.path.abspath(r) for r in cfg.roots}

    # 目录 -> 该目录下的直接文件名集合
    names_by_dir: dict = {}
    for r in con.execute("SELECT parent, name FROM files"):
        names_by_dir.setdefault(r["parent"], set()).add(r["name"])

    found: dict = {}

    def mark(path: str, tags: set) -> None:
        if path in found:
            found[path] |= tags
        else:
            found[path] = set(tags)

    for d in dirs:
        names = names_by_dir.get(d, set())
        tags = set()
        for marker, tag in MARKERS.items():
            if marker in names:
                tags.add(tag)
        for n in names:
            e = os.path.splitext(n)[1].lower()
            if e in MARKER_EXT:
                tags.add(MARKER_EXT[e])
        if os.path.isdir(os.path.join(d, ".git")):
            tags.add("Git")
        if tags:
            mark(d, tags)

    # 顶层「作品文件夹」：根目录下第一层，本身不是代码项目，但装了不少东西
    counts: dict = {}
    for r in con.execute("SELECT parent, count(*) c FROM files GROUP BY parent"):
        counts[r["parent"]] = r["c"]
    subtree: dict = {}
    for d, c in counts.items():
        cur = d
        while True:
            subtree[cur] = subtree.get(cur, 0) + c
            nxt = os.path.dirname(cur)
            if nxt == cur or cur in roots:
                break
            cur = nxt

    for d in list(subtree):
        parent = os.path.dirname(d)
        if parent in roots and d not in found and subtree.get(d, 0) >= 4:
            mark(d, {"文件夹"})

    # 一个安卓工程会在 repo/ 、repo/app/ 、repo/app/src/main/ 三层都留下标记，
    # 结果同一个项目被数成三个。只留最外层那个。
    code_paths = sorted((p for p, t in found.items() if "文件夹" not in t), key=len)
    kept_code: list = []
    for p in code_paths:
        if any(p.startswith(anc + os.sep) for anc in kept_code):
            continue
        kept_code.append(p)
    kept_code_set = set(kept_code)

    out = []
    for path, tags in found.items():
        if "文件夹" not in tags:
            if path not in kept_code_set:
                continue
        else:
            # 顶层文件夹里如果已经有正经项目，就让项目出面，别再报一个大筐
            if any(c.startswith(path + os.sep) for c in kept_code_set):
                continue
        out.append({"path": path, "tags": tags})
    return out


def rebuild(con, cfg: Config) -> int:
    """重算 projects 表并回填 files.project_id。"""
    con.execute("DELETE FROM projects")
    projects = detect(con, cfg)
    if not projects:
        con.execute("UPDATE files SET project_id=NULL")
        con.commit()
        return 0

    paths = sorted((p["path"] for p in projects), key=len, reverse=True)
    pid_by_path: dict = {}

    for p in projects:
        path = p["path"]
        name = os.path.basename(path.rstrip("\\/")) or path
        agg = con.execute(
            "SELECT count(*) c, coalesce(sum(size),0) s, coalesce(max(mtime),0) mx,"
            " coalesce(min(mtime),0) mn FROM files WHERE path LIKE ? ESCAPE '\\'",
            (_like_prefix(path),),
        ).fetchone()
        langs = {}
        for r in con.execute(
            "SELECT ext, count(*) c FROM files WHERE path LIKE ? ESCAPE '\\'"
            " GROUP BY ext ORDER BY c DESC LIMIT 24", (_like_prefix(path),)
        ):
            lang = LANG_BY_EXT.get(r["ext"])
            if lang:
                langs[lang] = langs.get(lang, 0) + r["c"]
        tags = sorted(p["tags"] - {"Git"})
        top = [k for k, _ in sorted(langs.items(), key=lambda kv: -kv[1])[:3]]
        branch, gitlast = _git_info(path)
        cur = con.execute(
            "INSERT OR IGNORE INTO projects(path,name,slug,version,kinds,file_count,size,"
            "mtime,ctime,span,is_git,git_branch) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (path, name, slugify(name), version_of(name),
             ",".join(dict.fromkeys(top + tags)), agg["c"], agg["s"],
             max(agg["mx"], gitlast), agg["mn"], agg["mx"] - agg["mn"],
             1 if branch else 0, branch),
        )
        if cur.lastrowid:
            pid_by_path[path] = cur.lastrowid

    for r in con.execute("SELECT id, path FROM projects"):
        pid_by_path[r["path"]] = r["id"]

    # 每个文件归给最深的那个项目
    cache: dict = {}

    def owner(parent: str):
        if parent in cache:
            return cache[parent]
        for pp in paths:
            if parent == pp or parent.startswith(pp + os.sep):
                cache[parent] = pid_by_path.get(pp)
                return cache[parent]
        cache[parent] = None
        return None

    updates = []
    for r in con.execute("SELECT DISTINCT parent FROM files"):
        pid = owner(r["parent"])
        if pid:
            updates.append((pid, r["parent"]))
    con.execute("UPDATE files SET project_id=NULL")
    con.executemany("UPDATE files SET project_id=? WHERE parent=?", updates)
    con.commit()
    return len(projects)


# 解压包 / 安装目录的特征：几百上千个文件，改动时间挤在同一小段里，
# 因为它们是被一次性写出来的。你自己做的东西，时间总是散开的。
UNPACKED_SPAN = 2 * 3600
UNPACKED_MIN_FILES = 30


def looks_unpacked(file_count: int, span: float) -> bool:
    return file_count >= UNPACKED_MIN_FILES and span < UNPACKED_SPAN


def _like_prefix(path: str) -> str:
    esc = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return esc + "\\\\%"


# ----------------------------------------------------------------- 版本簇
# 参与聚簇的文件类别：只看你自己产出的东西
CLUSTER_KINDS = ("doc", "slide", "sheet", "pdf", "archive")
MIN_SLUG = 3
# 通用名字，每个项目都有一份是天经地义的，不构成「堆积」
GENERIC_SLUGS = {
    "readme", "index", "main", "app", "config", "settings", "package",
    "public", "client", "server", "src", "files", "file", "assets", "static",
    "images", "image", "img", "css", "js", "lib", "libs", "docs", "doc",
    "documentation", "manual", "guide", "help", "info",
    "test", "tests", "example", "examples", "demo", "output", "outputs",
    "input", "inputs", "log", "logs", "notes", "note", "todo", "license",
    "changelog", "makefile", "requirements", "styles", "style", "utils",
    "components", "pages", "api", "core", "common", "temp", "backup",
    "新建文件夹", "未命名", "untitled", "document", "文档", "图片", "总",
    "资料", "素材", "作业", "笔记", "截图", "照片", "视频", "音频", "其他",
}


def _third_party(path: str) -> bool:
    return is_third_party(path)


def _slug_ok(s: str) -> bool:
    if len(s) >= MIN_SLUG:
        return True
    # 中文两个字已经很有信息量（如「课表」），但一个字不行
    return len(s) >= 2 and all("一" <= c <= "鿿" for c in s)


def clusters(con, min_members: int = 2) -> list:
    """把同一件东西的多个版本聚到一起。

    刻意保守：宁可漏，不可把「模组文件夹里本来就该有三份 jar」报成你的问题。
    只看项目目录，以及你自己写的文档 / 打的包，并且要求同一后缀。
    """
    buckets: dict = {}

    for r in con.execute(
        "SELECT id, path, name, slug, version, file_count, size, mtime, kinds FROM projects"
    ):
        if not_my_work(r["path"]) or not _slug_ok(r["slug"]):
            continue
        buckets.setdefault(("dir", r["slug"]), []).append({
            "type": "project", "id": r["id"], "path": r["path"], "name": r["name"],
            "version": r["version"], "size": r["size"], "mtime": r["mtime"],
            "file_count": r["file_count"], "kind": "project",
        })

    ph = ",".join("?" * len(CLUSTER_KINDS))
    for r in con.execute(
        "SELECT id, path, name, ext, size, mtime, kind FROM files WHERE kind IN (%s)" % ph,
        CLUSTER_KINDS,
    ):
        if not_my_work(r["path"]):
            continue
        stem = os.path.splitext(r["name"])[0]
        s = slugify(stem)
        if not _slug_ok(s):
            continue
        # 同后缀才算同一件东西：node.msi 和 node.exe 不是两个版本
        buckets.setdefault((r["ext"], s), []).append({
            "type": "file", "id": r["id"], "path": r["path"], "name": r["name"],
            "version": version_of(stem), "size": r["size"], "mtime": r["mtime"],
            "kind": r["kind"], "file_count": 1,
        })

    out = []
    for (_ext, slug), members in buckets.items():
        if len(members) < min_members or len({m["path"] for m in members}) < min_members:
            continue
        if slug in GENERIC_SLUGS:
            continue
        # 名字一模一样的多份是「副本」，不是「版本」——那归重复检测管。
        # 真正的版本堆积，要么名字有差别，要么带得出版本号。
        if len({m["name"] for m in members}) < 2 and not any(m["version"] for m in members):
            continue
        members.sort(key=lambda m: (_vkey(m["version"]), m["mtime"]), reverse=True)
        keep = members[0]
        total = sum(m["size"] for m in members)
        out.append({
            "slug": slug,
            "title": keep["name"],
            "kind": keep["kind"],
            "keep_path": keep["path"],
            "count": len(members),
            "bytes": total,
            "waste": total - keep["size"],   # 只留最新的那份能省下多少
            "newest": max(m["mtime"] for m in members),
            "span_days": round((max(m["mtime"] for m in members)
                                - min(m["mtime"] for m in members)) / 86400),
            "members": members,
        })
    out.sort(key=lambda c: (-c["count"], -c["waste"]))
    return out


def duplicates(con, limit: int = 200) -> list:
    """正文完全相同、但文件名/位置不同的文件。"""
    # 先多取一些再筛：排在前面的往往整组都在微信缓存里，
    # 若按 limit 截断后再过滤，真正属于你的重复会被挤掉。
    rows = con.execute(
        "SELECT fp, count(*) c, sum(size) s FROM files"
        " WHERE fp <> '' AND fp IS NOT NULL AND text_len > 200"
        " GROUP BY fp HAVING c > 1 ORDER BY s DESC LIMIT ?", (max(limit * 20, 2000),)
    ).fetchall()
    out = []
    for r in rows:
        members = [dict(m) for m in con.execute(
            "SELECT id, path, name, size, mtime, kind, text_len FROM files"
            " WHERE fp=? ORDER BY mtime DESC", (r["fp"],))]
        # 整组都在微信缓存 / 下载目录里，那是软件行为，不是你的重复。
        # 但只要有一份在你自己的文件夹，这组就值得看——「同一个 PPT
        # 在项目里、OneDrive 里、微信里各躺一份」正是要指出来的事。
        mine = [m for m in members if not not_my_work(m["path"])]
        if not mine:
            continue
        for m in members:
            m["mine"] = not not_my_work(m["path"])
        if len({m["name"] for m in members}) == 1:
            label = "同名副本"
        else:
            label = "改名副本"
        out.append({"fp": r["fp"], "count": r["c"], "bytes": r["s"],
                    "label": label, "own": len(mine), "members": members})
        if len(out) >= limit:
            break
    return out
