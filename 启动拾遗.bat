@echo off
setlocal
title 拾遗

cd /d "%~dp0"

rem 已经打包成 exe 就直接用 exe
if exist "dist\拾遗\拾遗.exe" (
  start "" "dist\拾遗\拾遗.exe"
  exit /b 0
)

set "PY="
where pythonw >nul 2>nul && set "PY=pythonw"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo.
  echo   没找到 Python。
  echo   请先安装 Python 3.10 以上版本，安装时记得勾选 "Add python.exe to PATH"。
  echo   下载： https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

start "" %PY% -X utf8 -m shiyi
exit /b 0
