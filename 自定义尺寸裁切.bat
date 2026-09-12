@echo off
chcp 936 >nul 2>&1
set PYTHONIOENCODING=gbk
setlocal
cd /d "%~dp0"

echo ============================================================
echo    自定义尺寸裁切  -  只裁图, 不配准
echo ============================================================
echo.
echo   本脚本只做裁切（裁掉黑边白边、摆正、统一尺寸），不做地理配准。
echo   文件名不需要任何规范。
echo.
echo   如果 input 文件夹里还没有图，请先把扫描件放进去。
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 没有找到 Python，请先安装并勾选 "Add Python to PATH"
    pause
    exit /b 1
)

REM ---------- 配置文件 ----------
if not exist "config.yaml" (
    if exist "config.example.yaml" (
        copy /y "config.example.yaml" "config.yaml" >nul
        echo   已自动创建 config.yaml
    ) else (
        echo [错误] 缺少 config.example.yaml
        pause
        exit /b 1
    )
)

REM ---------- 输入检查 ----------
set N=0
for %%f in ("input\*.jpg" "input\*.jpeg" "input\*.png" "input\*.tif" "input\*.tiff") do (
    if exist "%%~f" set /a N+=1
)
if %N%==0 (
    echo   [提示] input 文件夹里没有图片，请先放入扫描件。
    echo.
    pause
    exit /b 1
)
echo   找到 %N% 个图片文件
echo.

REM ---------- 让用户填尺寸 ----------
echo ============================================================
echo   请输入输出尺寸
echo ============================================================
echo.
echo   直接回车 = 用配置文件里的尺寸
echo.
echo   常用参考：
echo     3000x2000     较小，适合屏幕浏览
echo     4500x3500     默认值（对应 15' x 10' 的图幅比例）
echo     6000x4500     较大，适合打印
echo     original      不缩放，保持扫描原分辨率
echo.
echo   拿不准就在尺寸后加一个 k，例如 3000x2000k，
echo   表示"保持比例、居中补白"，绝不会拉伸变形。
echo.
set "SIZE="
set /p "SIZE=  尺寸(例如 4500x3500 或 3000x2000k): "

echo.
echo ------------------------------------------------------------
if "%SIZE%"=="" (
    echo   使用配置文件里的尺寸
    echo ------------------------------------------------------------
    echo.
    python scripts\01_crop.py
) else (
    echo   使用命令行尺寸： %SIZE%
    echo ------------------------------------------------------------
    echo.
    python scripts\01_crop.py -s %SIZE%
)

if errorlevel 1 (
    echo.
    echo   [错误] 出错了，请看上面的提示
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   完成！成果在 work\01_crop\ 里
echo   打开看看：黑边白边应该没了，图也摆正了
echo ============================================================
echo.
start "" "work\01_crop"
pause
