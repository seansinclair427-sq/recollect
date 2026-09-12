"""打出一个可以双击安装的 Windows 安装程序。

    python tools/build_installer.py

先把程序本体打成目录版，压成 payload.zip，再把这个 zip 连同安装界面
一起打成单个 exe。产物在 dist/ 下，形如 recollect-1.1.0-setup.exe。

安装程序自己不需要管理员权限：它装到 %LOCALAPPDATA%\\Programs 下。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
ICON = ROOT / "shiyi" / "web" / "icon.ico"
APP_NAME = "拾遗"

sys.path.insert(0, str(ROOT))
from shiyi import __version__                            # noqa: E402

# 文件名用 ASCII：GitHub 的 Release 资产会把中文字符整段丢掉，
# 上传 拾遗-1.1.0-安装程序.exe 到那边会变成 -1.1.0-.exe。
# 装完之后程序本身还是叫「拾遗」，这里只是外面那层壳的名字。
SETUP_NAME = "recollect-%s-setup" % __version__


def build_app() -> Path:
    """先有程序本体。"""
    sys.path.insert(0, str(ROOT / "tools"))
    import build_exe
    target = build_exe.build(onefile=False)
    app_dir = target.parent
    if not app_dir.is_dir():
        raise SystemExit("程序本体没打出来：%s" % app_dir)
    return app_dir


def pack(app_dir: Path) -> Path:
    """压成一个 zip。zip 里不带顶层目录 —— 解到哪儿就是哪儿。"""
    out = BUILD / "payload.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    files = sorted(f for f in app_dir.rglob("*") if f.is_file())
    total = sum(f.stat().st_size for f in files)
    print("正在压缩 %d 个文件（%.1f MB）……" % (len(files), total / 1e6))
    t0 = time.time()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in files:
            z.write(f, f.relative_to(app_dir).as_posix())
    print("压完 %.1f MB，用时 %.0f 秒" % (out.stat().st_size / 1e6,
                                          time.time() - t0))
    return out


def version_file() -> Path:
    nums = ([int(x) for x in __version__.split(".")] + [0, 0, 0, 0])[:4]
    text = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=%(t)s, prodvers=%(t)s, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080404B0', [
        StringStruct('CompanyName', '拾遗'),
        StringStruct('FileDescription', '拾遗 Recollect 安装程序'),
        StringStruct('FileVersion', '%(v)s'),
        StringStruct('InternalName', 'shiyi-setup'),
        StringStruct('LegalCopyright', 'MIT License'),
        StringStruct('OriginalFilename', '%(n)s.exe'),
        StringStruct('ProductName', '拾遗 Recollect'),
        StringStruct('ProductVersion', '%(v)s')])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""" % {"t": tuple(nums), "v": __version__, "n": SETUP_NAME}
    p = BUILD / "setup_version.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def build_setup(payload: Path) -> Path:
    entry = BUILD / "setup_entry.py"
    entry.write_text(
        "import sys\n"
        "from shiyi.installer import run_setup\n"
        "sys.exit(run_setup())\n", encoding="utf-8")

    args = [
        sys.executable, "-m", "PyInstaller", str(entry),
        "--name", SETUP_NAME,
        "--onefile",                       # 安装程序就该是一个文件
        "--noconsole",
        "--icon", str(ICON),
        "--version-file", str(version_file()),
        "--add-data", "%s;." % payload,
        "--add-data", "%s;shiyi/web" % (ROOT / "shiyi" / "web"),
        "--paths", str(ROOT),
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "setupwork"),
        "--specpath", str(BUILD),
        "--noconfirm", "--clean",
        # payload.zip 已经压过了，别让 PyInstaller 再压一遍（白费几十秒）
        "--noupx",
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        "--exclude-module", "test",
        "--exclude-module", "setuptools",
        "--exclude-module", "pip",
        "--exclude-module", "sqlite3",     # 安装程序不碰索引
        "--exclude-module", "xmlrpc",
        "--exclude-module", "doctest",
    ]
    print("开始打安装程序……")
    t0 = time.time()
    subprocess.check_call(args, cwd=str(ROOT))
    exe = DIST / (SETUP_NAME + ".exe")
    if not exe.is_file():
        raise SystemExit("安装程序没打出来")
    print("\n安装程序：%s" % exe)
    print("大小：%.1f MB，用时 %.0f 秒"
          % (exe.stat().st_size / 1e6, time.time() - t0))
    return exe


def main() -> int:
    ap = argparse.ArgumentParser(description="打包拾遗的安装程序")
    ap.add_argument("--skip-app", action="store_true",
                    help="程序本体已经在 dist/ 里了，直接用")
    ap.add_argument("--clean", action="store_true", help="先清掉 build/ 和 dist/")
    a = ap.parse_args()

    if sys.platform != "win32":
        print("警告：不在 Windows 上，产物大概率不能用。")
    if a.clean:
        for d in (DIST, BUILD):
            shutil.rmtree(d, ignore_errors=True)

    app_dir = DIST / APP_NAME
    if a.skip_app and app_dir.is_dir():
        print("沿用已有的 %s" % app_dir)
    else:
        app_dir = build_app()

    build_setup(pack(app_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
