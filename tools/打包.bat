@echo off
setlocal
title 拾遗 - 打包
cd /d "%~dp0\.."
echo.
echo   打包拾遗：先出免安装的 dist\拾遗\，再出安装程序。
echo   第一次会自动装 PyInstaller，需要联网。
echo.
set "PY=python"
where python >nul 2>nul || set "PY=py"
%PY% -X utf8 tools\build_installer.py %*
echo.
pause
