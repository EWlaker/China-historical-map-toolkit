@echo off
chcp 936 >nul 2>&1
set PYTHONIOENCODING=gbk
setlocal
cd /d "%~dp0"
title 拼图工作台 - 请不要关闭这个窗口

echo ============================================================
echo    拼图工作台  -  把切好的图拖成一张完整的图
echo ============================================================
echo.
echo   接下来会自动打开浏览器。你在网页里像拼拼图一样，
echo   把缩略图拖到正确位置，然后点  "一键生成拼图"  就行了。
echo.
echo   不用下载任何文件，也不用敲命令。
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo   [错误] 没有找到 Python
    echo.
    echo   请先安装 Python：https://www.python.org/downloads/
    echo   安装时务必勾选  "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

REM ---------- 检查有没有裁好的图 ----------
if not exist "work\01_crop" (
    echo   [提示] 还没有裁好的图。
    echo.
    echo   请先做这两步：
    echo     1. 把扫描件放进 input 文件夹
    echo     2. 双击  "一键运行.bat"  把它们裁开
    echo.
    echo   然后回来再双击本文件。
    echo.
    pause
    exit /b 1
)

set N=0
for %%f in ("work\01_crop\*_inner.png") do set /a N+=1
if %N%==0 (
    echo   [提示] work\01_crop 里没有裁好的图。
    echo.
    echo   请先双击  "一键运行.bat"  把扫描件裁开，再回来。
    echo.
    pause
    exit /b 1
)

echo   找到 %N% 幅裁好的图，正在启动...
echo.

REM 起本地服务 + 自动打开浏览器（服务会一直运行，直到你关掉本窗口）
python scripts\tools\make_puzzle.py --serve

echo.
echo ============================================================
echo   工作台已关闭。
echo ============================================================
echo.
pause
