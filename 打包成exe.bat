@echo off
setlocal
title 拾遗 - 打包成 exe
cd /d "%~dp0"
echo.
echo   把拾遗打包成不需要 Python 的 Windows 程序。
echo   第一次会自动装 PyInstaller，需要联网。
echo.
set "PY=python"
where python >nul 2>nul || set "PY=py"
%PY% -X utf8 tools\build_exe.py %*
echo.
pause
