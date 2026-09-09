@echo off
setlocal
title 拾遗

cd /d "%~dp0"

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py"
if not defined PY (
  echo.
  echo   没找到 Python。
  echo   请先安装 Python 3.10 以上版本，安装时记得勾选 "Add python.exe to PATH"。
  echo   下载： https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

echo.
echo   拾遗正在启动，浏览器会自动打开。
echo   关掉这个窗口就停止。
echo.

%PY% -X utf8 -m shiyi serve
if errorlevel 1 (
  echo.
  echo   启动失败。把上面的报错发出来就能查。
  echo.
  pause
)
