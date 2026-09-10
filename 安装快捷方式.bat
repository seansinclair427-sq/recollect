@echo off
setlocal
title 拾遗 - 安装
cd /d "%~dp0"
echo.
echo   给拾遗创建桌面和开始菜单快捷方式。
echo   不需要管理员权限，只写当前用户。
echo.
set "PY=python"
where python >nul 2>nul || set "PY=py"
%PY% -X utf8 -m shiyi install
echo.
pause
