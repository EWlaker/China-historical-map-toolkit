@echo off
chcp 936 >nul 2>&1
set PYTHONIOENCODING=gbk
setlocal
cd /d "%~dp0"

echo ============================================================
echo    拼图工作台  -  把切好的图拖成一张完整的图
echo ============================================================
echo.
echo   这一步会生成一个网页，你在网页里像拼拼图一样
echo   把缩略图拖到正确位置，就能拼成整张地图。
echo.
echo   不需要任何命令，跟着提示走就行。
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

echo   找到 %N% 幅裁好的图。
echo.
echo ------------------------------------------------------------
echo   正在生成拼图网页，请稍等...
echo ------------------------------------------------------------
echo.

python scripts\tools\make_puzzle.py
if errorlevel 1 (
    echo.
    echo   [错误] 生成失败，请看上面的提示。
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   好了！现在正在打开拼图网页...
echo ============================================================
echo.
echo   在网页里这样操作：
echo.
echo     1. 先点右上角  "自动排布"   把图铺开
echo     2. 拖动缩略图，摆到正确位置
echo        （看省界、河流、道路能不能接上）
echo     3. 摆好后点  "导出布局"
echo     4. 在弹出的窗口里点  "下载 JSON"
echo.
echo   滚轮缩放  /  空白处拖动平移  /  双击图块退回
echo.
echo   下载完成后，回到这个文件夹双击  "拼接成果.bat"
echo   就能拼成一张完整的图。
echo.
pause

start "" "puzzle.html"
