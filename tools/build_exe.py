"""把拾遗打成一个不需要装 Python 的 Windows 程序。

    python tools/build_exe.py            目录版（启动快，推荐自己用）
    python tools/build_exe.py --onefile  单文件版（一个 exe，方便发给别人）

产物在 dist/ 下。构建需要 pyinstaller；运行时仍然零依赖。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
ICON = ROOT / "shiyi" / "web" / "icon.ico"
NAME = "拾遗"


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
        return
    except ImportError:
        pass
    print("没装 PyInstaller，正在安装……")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "pyinstaller>=6.0", "-q",
        "-i", "https://mirrors.aliyun.com/pypi/simple/",
    ])


def ensure_icon() -> None:
    if ICON.is_file():
        return
    print("图标不在，先生成……")
    sys.path.insert(0, str(ROOT / "tools"))
    import make_icon
    make_icon.build(ICON)


def version_file() -> Path:
    """写一个版本资源，右键属性里能看到，也让杀软少点疑心。"""
    sys.path.insert(0, str(ROOT))
    from shiyi import __version__
    nums = ([int(x) for x in __version__.split(".")] + [0, 0, 0, 0])[:4]
    text = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=%(t)s, prodvers=%(t)s, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080404B0', [
        StringStruct('CompanyName', '拾遗'),
        StringStruct('FileDescription', '拾遗 —— 本地作品档案馆'),
        StringStruct('FileVersion', '%(v)s'),
        StringStruct('InternalName', 'shiyi'),
        StringStruct('LegalCopyright', 'MIT License'),
        StringStruct('OriginalFilename', '%(n)s.exe'),
        StringStruct('ProductName', '拾遗'),
        StringStruct('ProductVersion', '%(v)s')])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""" % {"t": tuple(nums), "v": __version__, "n": NAME}
    p = BUILD / "version_info.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def build(onefile: bool) -> Path:
    ensure_icon()
    ensure_pyinstaller()
    vf = version_file()

    entry = BUILD / "shiyi_entry.py"
    entry.write_text(
        "import multiprocessing, sys\n"
        "multiprocessing.freeze_support()\n"
        "from shiyi.app import main\n"
        "sys.exit(main())\n", encoding="utf-8")

    args = [
        sys.executable, "-m", "PyInstaller",
        str(entry),
        "--name", NAME,
        "--noconsole",                       # 托盘程序不需要黑窗口
        "--icon", str(ICON),
        "--version-file", str(vf),
        "--add-data", "%s%s%s" % (ROOT / "shiyi" / "web", ";", "shiyi/web"),
        "--paths", str(ROOT),
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        "--noconfirm", "--clean",
        # 用不到的大件排掉。注意 email 不能排 —— http.server 依赖它，
        # 排掉之后 exe 能启动但一 import 就 ModuleNotFoundError。
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        "--exclude-module", "test",
        "--exclude-module", "distutils",
        "--exclude-module", "setuptools",
        "--exclude-module", "pip",
        "--exclude-module", "xmlrpc",
        "--exclude-module", "pdb",
        "--exclude-module", "doctest",
    ]
    args.append("--onefile" if onefile else "--onedir")

    print("开始构建（%s）……" % ("单文件" if onefile else "目录版"))
    t0 = time.time()
    subprocess.check_call(args, cwd=str(ROOT))

    target = DIST / ("%s.exe" % NAME) if onefile else DIST / NAME / ("%s.exe" % NAME)
    print("\n构建完成，用时 %.0f 秒" % (time.time() - t0))
    if target.exists():
        print("产物：%s" % target)
        print("大小：%.1f MB" % (_tree_size(target) / 1e6))
    return target


def _tree_size(exe: Path) -> int:
    if exe.parent.name == NAME:
        return sum(f.stat().st_size for f in exe.parent.rglob("*") if f.is_file())
    return exe.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser(description="打包拾遗")
    ap.add_argument("--onefile", action="store_true",
                    help="打成单个 exe（启动稍慢，但方便分发）")
    ap.add_argument("--clean", action="store_true", help="先清掉 build/ 和 dist/")
    a = ap.parse_args()
    if a.clean:
        for d in (DIST, BUILD):
            shutil.rmtree(d, ignore_errors=True)
    if sys.platform != "win32":
        print("警告：不在 Windows 上，产物大概率不能用。")
    build(a.onefile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
