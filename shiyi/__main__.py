"""python -m shiyi

不带子命令时直接当软件启动（托盘 + 窗口）；带子命令时走命令行。
--help / --version 这类要交给命令行处理，否则问个帮助反而把程序拉起来了。
"""
import sys

_CLI_FLAGS = {"-h", "--help", "-V", "--version"}
_argv = sys.argv[1:]

if _argv and (not _argv[0].startswith("-") or _argv[0] in _CLI_FLAGS):
    from .cli import main
    raise SystemExit(main())

from .app import main as app_main
raise SystemExit(app_main())
