@echo off
chcp 936 >nul 2>&1
rem 本文件为 GBK 编码, 并把 Python 输出也统一到 GBK, 避免中文乱码
set PYTHONIOENCODING=gbk
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo    历史地形图批量裁切与配准  -  一键运行
echo ============================================================
echo.

REM ---------- 第 1 步: 检查 Python ----------
echo [1/6] 检查 Python ...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [错误] 没有找到 Python
    echo.
    echo   请先安装 Python，步骤：
    echo     1. 打开 https://www.python.org/downloads/
    echo     2. 下载并运行安装程序
    echo     3. 安装第一屏务必勾选  "Add Python to PATH"
    echo     4. 装完后重新双击本文件
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo        %%v  已就绪

REM ---------- 第 2 步: 检查依赖库 ----------
echo.
echo [2/6] 检查依赖库 ...
python -c "import cv2, numpy, rasterio, yaml, PIL" >nul 2>&1
if errorlevel 1 (
    echo        缺少依赖库，正在自动安装（需要联网，约 1-3 分钟）...
    echo.
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo   [错误] 依赖安装失败
        echo   常见原因：没联网 / 网络被墙 / pip 太旧
        echo   可尝试手动执行：
        echo     python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        echo.
        pause
        exit /b 1
    )
    echo.
    echo        依赖安装完成
) else (
    echo        依赖库已就绪，无需安装
)

REM ---------- 第 3 步: 确认配置文件 ----------
echo.
echo [3/6] 检查配置文件 config.yaml ...
if not exist "config.yaml" (
    if exist "config.example.yaml" (
        copy /y "config.example.yaml" "config.yaml" >nul
        echo        未找到 config.yaml，已自动从模板创建
    ) else (
        echo.
        echo   [错误] 缺少 config.example.yaml，工具包不完整
        echo.
        pause
        exit /b 1
    )
) else (
    echo        config.yaml 已存在
)

REM ---------- 第 4 步: 确认有图片 ----------
echo.
echo [4/6] 检查输入目录 input\ ...
set N=0
for %%f in ("input\*.jpg" "input\*.jpeg" "input\*.png" "input\*.tif" "input\*.tiff") do (
    if exist "%%~f" set /a N+=1
)
if !N!==0 (
    echo.
    echo   [提示] input 文件夹里没有图片
    echo.
    echo   请把你的地图扫描件（jpg/png/tif）放进 input 文件夹，然后重新运行。
    echo   如果想先试试效果，请双击 "生成示例数据.bat"
    echo.
    pause
    exit /b 1
)
echo        找到 !N! 个图片文件

REM ---------- 第 5 步: 开始处理 ----------
echo.
echo [5/6] 开始处理（幅数多时需要较长时间，请耐心等待）
echo.
echo ------------------------------------------------------------
echo  第 1 关 / 共 3 关：裁切（纠斜 + 找图廓 + 裁到内容）
echo ------------------------------------------------------------
python scripts\01_crop.py
if errorlevel 1 (
    echo.
    echo   [错误] 裁切过程出错，请把上面的报错内容发给技术人员
    pause
    exit /b 1
)

echo.
echo ------------------------------------------------------------
echo  第 2 关 / 共 3 关：配准（算出每幅图该在的经纬度）
echo ------------------------------------------------------------
python scripts\02_georef.py
if errorlevel 1 (
    echo.
    echo   [错误] 配准过程出错
    echo   如果提示"文件名不符合规则"，说明你的文件命名和配置对不上，
    echo   请看 "新手从这里开始.md" 第三节。
    pause
    exit /b 1
)

echo.
echo ------------------------------------------------------------
echo  第 3 关 / 共 3 关：生成拼接索引
echo ------------------------------------------------------------
python scripts\03_build_vrt.py

REM ---------- 第 6 步: 自查 ----------
echo.
echo [6/6] 自查 ...
python scripts\tools\check_outputs.py

echo.
echo ============================================================
echo    全部完成！
echo.
echo    成果位置：
echo      work\01_crop\   裁切好的图（普通图片，可直接看）
echo      work\02_geo\    带坐标的图（GIS 软件打开）
echo      work\02_geo\mosaic.vrt   拼接索引（QGIS 里拖进去看整体）
echo ============================================================
echo.
echo 正在打开成果文件夹 ...
start "" "work"
echo.
pause
