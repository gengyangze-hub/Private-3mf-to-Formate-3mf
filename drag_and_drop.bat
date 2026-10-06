@echo off
if not defined B3MF_UTF8 (
    chcp 65001 >nul
    set "B3MF_UTF8=1"
    cmd /c ""%~f0" %*"
    exit /b
)
setlocal
title Bambu3MF 一键转彩色

if "%~1"=="" goto :noargs

set "PYEXE="

py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYEXE=py -3"

if not defined PYEXE (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE (
    for /f "delims=" %%P in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\python.exe" 2^>nul') do (
        if not defined PYEXE set "PYEXE=%%P"
    )
)

if not defined PYEXE goto :nopython

echo 使用 Python：%PYEXE%
echo 正在转换，请稍等几秒……
echo.
%PYEXE% "%~dp0convert.py" %*
echo.
echo ============================================================
echo  转换结束。带颜色的文件就在每个 3mf 旁边的
echo  「原文件名_color」文件夹里，里面有：
echo     原文件名_color.3mf    ← 传给嘉立创用这个
echo     原文件名_color.zip    ← 压缩包（内含 3mf 和 obj+mtl）
echo     原文件名_color.obj 和 原文件名_color.mtl
echo ============================================================
echo.
pause
exit /b 0

:noargs
echo.
echo   用法：把 .3mf 文件（可以一次多选好几个）拖到本文件上，松手即可。
echo.
echo   如果双击打开了本窗口，说明没有拖入文件。
echo   请关掉本窗口，改为把 3mf 文件拖到「拖拽转换.bat」图标上。
echo.
pause
exit /b 0

:nopython
echo.
echo   [错误] 没有找到 Python 3。
echo.
echo   请先安装 Python 3 并勾选 Add to PATH
echo   下载地址 https://www.python.org/downloads/windows/
echo   安装界面最下面一定要勾选 Add python.exe to PATH 。
echo.
pause
exit /b 1
