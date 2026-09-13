@echo off
chcp 936 >nul 2>&1
set PYTHONIOENCODING=gbk
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo    拼接成果  -  把拼图结果拼成一张整图
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo   [错误] 没有找到 Python，请先安装。
    pause
    exit /b 1
)

REM ---------- 找布局文件 ----------
set "LAYOUT="
if exist "puzzle_layout.json" set "LAYOUT=puzzle_layout.json"

if not defined LAYOUT (
    echo   正在查找 puzzle_layout.json ...
    for %%d in ("%USERPROFILE%\Downloads" "%USERPROFILE%\Desktop" "%USERPROFILE%\Documents" ".") do (
        if not defined LAYOUT (
            if exist "%%~d\puzzle_layout.json" set "LAYOUT=%%~d\puzzle_layout.json"
        )
    )
)

if not defined LAYOUT (
    echo.
    echo   [提示] 没有找到 puzzle_layout.json
    echo.
    echo   这个文件是拼图网页里点  "导出布局" -^> "下载 JSON"  得到的。
    echo.
    echo   请先双击  "拼图工作台.bat"  摆好位置并下载它，
    echo   或者把它复制到本文件夹里，再双击本文件。
    echo.
    pause
    exit /b 1
)

echo   找到布局文件: !LAYOUT!
echo.

REM ---------- 让用户选清晰度 ----------
echo ============================================================
echo   选择成果的清晰度
echo ============================================================
echo.
echo     1 = 预览    体积小，几秒钟就好，用来检查拼得对不对   【推荐先选这个】
echo     2 = 清晰    适合在电脑上看、放进 PPT
echo     3 = 打印    体积较大，适合打印出来
echo     4 = 存档    原始分辨率，体积最大，可能要等一会儿
echo.
set "Q=1"
set /p "Q=  请输入 1 / 2 / 3 / 4，直接回车 = 1 : "

set "ARG="
if "!Q!"=="2" set "ARG=-s 0.6 --jpg"
if "!Q!"=="3" set "ARG=-s 0.8 --jpg"
if "!Q!"=="4" set "ARG=--jpg"
if "!Q!"=="1" set "ARG=-s 0.35 --jpg"
if not defined ARG set "ARG=-s 0.35 --jpg"

echo.
echo ------------------------------------------------------------
echo   正在拼接，请稍等...
echo ------------------------------------------------------------
echo.

python scripts\tools\assemble_by_layout.py "!LAYOUT!" !ARG!
if errorlevel 1 (
    echo.
    echo   [错误] 拼接失败，请看上面的提示。
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   拼好了！正在打开成果文件夹...
echo ============================================================
echo.
echo   成果在 work\03_assembly 文件夹里。
echo.
echo   注意：这张图没有地理坐标，是一张纯粹拼接起来的图片。
echo         如果你想让它能叠加到卫星影像上分析，
echo         需要图号或接图表，见 docs\命名规则与接图表.md
echo.
pause

if exist "work\03_assembly" start "" "work\03_assembly"
