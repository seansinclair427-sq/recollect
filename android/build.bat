@echo off
rem ============================================================
rem  拾遗 安卓版 · 一键编译（Windows）
rem
rem  为什么不能直接跑 gradlew：本机 %LOCALAPPDATA%\Temp 下 AF_UNIX 连不上，
rem  JVM 的 Selector.open() 会失败，Gradle 直接报
rem      Unable to establish loopback connection
rem  这里把 TEMP 挪到一个没有空格的路径再调 gradlew。
rem
rem  用法:  build.bat            编译 debug
rem         build.bat release    编译 release（需要 app\shiyi.jks）
rem         build.bat install    编译并 adb 安装到已连接的设备
rem ============================================================
setlocal

if not defined SHIYI_JDK set "SHIYI_JDK=C:\Program Files\Android\Android Studio\jbr"
if not exist "%SHIYI_JDK%\bin\java.exe" (
    echo [错误] 找不到 JDK: %SHIYI_JDK%
    echo        设置环境变量 SHIYI_JDK 指向一个 JDK 17+ 再试。
    exit /b 1
)
set "JAVA_HOME=%SHIYI_JDK%"

if not defined SHIYI_TMP set "SHIYI_TMP=C:\gradle-tmp"
if not exist "%SHIYI_TMP%" mkdir "%SHIYI_TMP%"
set "TEMP=%SHIYI_TMP%"
set "TMP=%SHIYI_TMP%"

cd /d "%~dp0"
echo JAVA_HOME = %JAVA_HOME%
echo TEMP      = %TEMP%
echo.

if /i "%~1"=="release"  ( call gradlew.bat assembleRelease & goto :done )
if /i "%~1"=="install"  ( call gradlew.bat installDebug    & goto :done )
if /i "%~1"=="clean"    ( call gradlew.bat clean           & goto :done )
if "%~1"==""            ( call gradlew.bat assembleDebug   & goto :done )
call gradlew.bat %*

:done
set RC=%ERRORLEVEL%
echo.
if %RC%==0 (
    echo 编译完成。APK 在 app\build\outputs\apk\ 下。
) else (
    echo 编译失败，退出码 %RC%
)
exit /b %RC%
