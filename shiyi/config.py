"""配置：索引根目录、忽略规则、文件分类。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

HOME = Path.home()
DATA_DIR = Path(os.environ.get("SHIYI_HOME") or (HOME / ".shiyi"))
DB_PATH = DATA_DIR / "shiyi.db"
CONFIG_PATH = DATA_DIR / "config.json"

# ---------------------------------------------------------------- 忽略规则
# 目录名精确匹配即整棵剪掉。顺序无关，命中即停。
IGNORE_DIRS = {
    # 依赖 / 构建产物
    "node_modules", "bower_components", "vendor", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", ".nox", "site-packages", "dist-info",
    "build", "dist", "out", "target", "bin", "obj", ".next", ".nuxt", ".parcel-cache",
    ".gradle", ".idea", ".vs", ".vscode-test", "cmake-build-debug", "DerivedData",
    # 版本控制 / 缓存
    ".git", ".svn", ".hg", ".cache", ".venv", "venv", "env", ".env",
    "AppData", "Application Data", "$RECYCLE.BIN", "System Volume Information",
    # 运行时 / 大型不可读
    ".ollama", ".rustup", ".cargo", ".nuget", ".gradle", ".android", ".dotnet",
    ".deepcode", ".u2net", ".chocolatey", ".claude", ".codex", ".conda",
    "Temp", "tmp", "logs", "log", "Crashpad", "GPUCache", "Code Cache",
    # 游戏 / 大体积资源库（用户机器上确实存在）
    "versions", "libraries", "assets", "saves", "resourcepacks", "shaderpacks",
}
# 目录名以此开头也剪掉
IGNORE_DIR_PREFIXES = ("~$", ".dart_tool", "node-v")

IGNORE_FILE_PREFIXES = ("~$", ".~lock.")
IGNORE_FILE_NAMES = {"NTUSER.DAT", "ntuser.dat", "desktop.ini", "Thumbs.db", ".DS_Store"}

# ---------------------------------------------------------------- 分类
KIND_BY_EXT = {}
def _reg(kind: str, exts: str) -> None:
    for e in exts.split():
        KIND_BY_EXT["." + e] = kind

_reg("doc",     "docx doc rtf odt md markdown txt text log tex")
_reg("slide",   "pptx ppt odp key")
_reg("sheet",   "xlsx xls csv tsv ods")
_reg("pdf",     "pdf")
_reg("code",    "py js jsx ts tsx java kt kts c h cpp hpp cc cs go rs rb php swift "
                "lua sh bat ps1 sql r m mm dart vue svelte scala clj ex exs pl "
                "html htm css scss sass less json yaml yml toml ini cfg conf xml "
                "gradle properties cmake mk makefile ino pde asm vb")
_reg("image",   "png jpg jpeg gif webp bmp svg ico tiff tif psd ai heic avif")
_reg("video",   "mp4 mkv avi mov wmv flv webm m4v")
_reg("audio",   "mp3 wav flac aac ogg m4a wma mid")
_reg("archive", "zip rar 7z tar gz bz2 xz iso")
_reg("app",     "exe msi apk ipa appx dmg deb jar")
_reg("font",    "ttf otf woff woff2")

# 会被抽取正文的类别
TEXTUAL_KINDS = {"doc", "slide", "sheet", "pdf", "code"}

# ---------------------------------------------------------------- 正文过滤
# 这些是「别人的代码 / 机器生成的东西」，索引它们只会淹没你自己写的字。
VENDOR_DIR_SUFFIXES = ("-main", "-master", "-src", ".egg-info")
# 工具链 / 运行时 / 游戏数据：文件名仍然入索引（你可能就是想找它），
# 但不抽正文——否则一个 Mixly 安装包就能往索引里灌几十兆别人的文档。
VENDOR_PATH_SEGMENTS = {
    "mingw32", "mingw64", "portablegit", "msys64", "cygwin",
    "toolchain", "toolchains", "sdk", "ndk", "jdk", "jre", "dlls",
    "cpython", "python27", "python3", "pythonwin", "tcl", "tk",
    "man", "man1", "man3", "info", "texmf", "texlive",
    "localisation", "localization", "locale", "locales", "i18n", "lang",
    "wiki", "gfx", "interface", "history", "gamedata",
    "third_party", "thirdparty", "external", "deps", "vendored",
}
# 单个目录能贡献的正文总量上限。数据堆总是扁平的一大坨；
# 正常人的一个文件夹里不会有 4MB 纯文字。
MAX_DIR_TEXT_BYTES = 4_000_000
GENERATED_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock",
    "Cargo.lock", "poetry.lock", "go.sum", "gradle.lockfile",
}
GENERATED_EXT_SUFFIX = (".min.js", ".min.css", ".map", ".d.ts", ".bundle.js",
                        ".chunk.js", ".lock")
# 超过这个大小的数据类文件不抽正文（多半是数据集，不是文章）
DATA_EXT_LIMIT = {".json": 120_000, ".csv": 400_000, ".tsv": 400_000,
                  ".xml": 300_000, ".sql": 300_000, ".txt": 300_000,
                  ".log": 200_000, ".yml": 120_000, ".yaml": 120_000,
                  ".html": 200_000, ".htm": 200_000}
CODE_TEXT_LIMIT = 80_000


def skip_content(path: str, size: int, kind: str) -> str:
    """要不要跳过正文抽取。返回跳过原因，空串表示照常抽。"""
    name = os.path.basename(path)
    if name in GENERATED_NAMES or name.lower().endswith(GENERATED_EXT_SUFFIX):
        return "generated"
    parts = path.replace("/", "\\").split("\\")
    lower = [p.lower() for p in parts[:-1]]
    if any(p.endswith(VENDOR_DIR_SUFFIXES) for p in lower):
        return "vendor"
    if any(p in VENDOR_PATH_SEGMENTS for p in lower):
        return "vendor"
    ext = os.path.splitext(name)[1].lower()
    cap = DATA_EXT_LIMIT.get(ext)
    if cap is not None and size > cap:
        return "data"
    if kind == "code" and size > CODE_TEXT_LIMIT:
        return "toobig"
    return ""


def looks_minified(text: str) -> bool:
    """一行几千字符、几乎没有换行 —— 打包产物。"""
    head = text[:20000]
    if not head:
        return False
    lines = head.count("\n") + 1
    return len(head) / lines > 400
# 「作品」——用户产出物，进年鉴
ARTIFACT_KINDS = {"doc", "slide", "sheet", "pdf", "app", "image", "video"}


def kind_of(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if not ext:
        base = os.path.basename(path).lower()
        if base in ("makefile", "dockerfile", "readme", "license"):
            return "code" if base in ("makefile", "dockerfile") else "doc"
        return "other"
    return KIND_BY_EXT.get(ext, "other")


# ---------------------------------------------------------------- 用户配置
def _default_roots() -> list[str]:
    cands = [HOME / "Documents", HOME / "Desktop", HOME / "Downloads", HOME / "OneDrive"]
    return [str(p) for p in cands if p.is_dir()]


@dataclass
class Config:
    roots: list[str] = field(default_factory=_default_roots)
    extra_ignores: list[str] = field(default_factory=list)
    max_text_bytes: int = 400_000       # 单文件抽取正文上限
    max_file_bytes: int = 120_000_000   # 超过此大小不打开
    index_content: bool = True
    port: int = 7331

    @classmethod
    def load(cls) -> "Config":
        if CONFIG_PATH.exists():
            try:
                raw = json.loads(CONFIG_PATH.read_text("utf-8"))
                known = {f for f in cls.__dataclass_fields__}
                return cls(**{k: v for k, v in raw.items() if k in known})
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), "utf-8"
        )

    def ignored_dir(self, name: str) -> bool:
        if name in IGNORE_DIRS or name in self.extra_ignores:
            return True
        return name.startswith(IGNORE_DIR_PREFIXES)
