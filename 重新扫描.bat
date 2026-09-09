@echo off
setlocal
title Ê°ÒÅ - ÖØÐÂÉ¨Ãè
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul || set "PY=py"
%PY% -X utf8 -m shiyi scan
echo.
pause
