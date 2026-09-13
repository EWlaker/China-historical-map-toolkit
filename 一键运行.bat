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

REM ---------- 命令行参数（高级用法，也可用于自动化测试）----------
REM   一键运行.bat /color gray /size original /geo 0
REM   给了任意一个参数就不再问，没给的用默认值。
set "ARG_COLOR="
set "ARG_SIZE="
set "ARG_GEO="
set "BATCH_MODE=0"

:PARSE
if "%~1"=="" goto PARSE_DONE
if /i "%~1"=="/color" (
    set "ARG_COLOR=%~2"
    set "BATCH_MODE=1"
    shift
    shift
    goto PARSE
)
if /i "%~1"=="/size" (
    set "ARG_SIZE=%~2"
    set "BATCH_MODE=1"
    shift
    shift
    goto PARSE
)
if /i "%~1"=="/geo" (
    set "ARG_GEO=%~2"
    set "BATCH_MODE=1"
    shift
    shift
    goto PARSE
)
shift
goto PARSE
:PARSE_DONE

REM ---------- 第 5 步: 问清楚三件事 ----------
if "!BATCH_MODE!"=="1" goto SKIP_ASK

echo.
echo ============================================================
echo   开始之前，先确认三件事（每题直接回车 = 用括号里的默认值）
echo ============================================================
echo.
echo   这三个没有"对错"，看你这批图要拿来干什么。
echo.

REM --- ① 色彩 ---
echo ------------------------------------------------------------
echo   [1/3] 输出色彩
echo ------------------------------------------------------------
echo     1 = 自动判断      黑白图出灰度、有颜色的图保住颜色   【默认，推荐】
echo     2 = 强制灰度      不管原图什么颜色，一律转成黑白
echo     3 = 强制彩色      一律保留颜色
echo.
echo     怎么选：地形图之类本来就是黑白的，选 1 就行；
echo             交通图、水系图这种"颜色本身就是信息"的，
echo             选 1 也会自动认出来。拿不准就用 1。
echo.
set "C=1"
set /p "C=  请选择 1 / 2 / 3 [1]: "


REM --- ② 尺寸 ---
echo.
echo ------------------------------------------------------------
echo   [2/3] 输出尺寸
echo ------------------------------------------------------------
echo     1 = 4500x3500     统一尺寸，配经纬度网格用          【默认】
echo     2 = 保持原始像素  不缩放，各幅尺寸可能不一致
echo     3 = 自己填        例如 3000x2000
echo.
echo     怎么选：要做地理配准（能进 GIS）就选 1；
echo             只想裁干净、不想缩放，选 2；
echo             不确定该多大，先跑 "python scripts\tools\probe_resolution.py"
echo             让它测一下你的扫描件实际是多少像素。
echo.
set "S=1"
set /p "S=  请选择 1 / 2 / 3 [1]: "


REM --- ③ 图号 ---
echo.
echo ------------------------------------------------------------
echo   [3/3] 这批图的文件名里有标准图号吗？
echo ------------------------------------------------------------
echo     1 = 有   形如  2108-瑪瑙觀.jpg
echo              （前两位是列号、后两位是行号，能算出经纬度）   【默认】
echo     2 = 没有 我要做地理配准，但文件名不是这个格式
echo     3 = 没有 我只要裁切，不需要经纬度
echo.
echo     怎么选：能算出经纬度才能进 GIS 叠加分析。
echo             如果文件名里没有图号、也查不到接图表，
echo             那这批图做不了配准 —— 选 3 只裁切，
echo             或者用 "拼图工作台.bat" 手工拼出位置关系。
echo.
set "G=1"
set /p "G=  请选择 1 / 2 / 3 [1]: "


goto ASK_DONE

:SKIP_ASK
REM 从参数取值（没给的用默认）；实际参数在下面的 :ASK_DONE 统一推导
set "C=1"
set "S=1"
set "G=1"
if /i "!ARG_COLOR!"=="gray"  set "C=2"
if /i "!ARG_COLOR!"=="color" set "C=3"
if /i "!ARG_COLOR!"=="auto"  set "C=1"
if /i "!ARG_SIZE!"=="original" set "S=2"
if not "!ARG_SIZE!"=="" if /i not "!ARG_SIZE!"=="original" set "S=3"
if "!ARG_GEO!"=="0" set "G=3"
if "!ARG_GEO!"=="1" set "G=1"

:ASK_DONE
REM ---------- 由 C / S / G 推导实际参数（问答和参数两条路共用）----------
set "CARGS="
if "!C!"=="2" set "CARGS=--color gray"
if "!C!"=="3" set "CARGS=--color color"
if not defined CARGS set "CARGS=--color auto"

set "SARGS="
if "!S!"=="1" set "SARGS=-s 4500x3500"
if "!S!"=="2" set "SARGS=-s original"
if "!S!"=="3" (
    if defined ARG_SIZE (
        set "SARGS=-s !ARG_SIZE!"
    ) else (
        set "CUSTOM="
        set /p "CUSTOM=  请输入尺寸(例如 3000x2000): "
        if defined CUSTOM set "SARGS=-s !CUSTOM!"
    )
)
if not defined SARGS set "SARGS=-s 4500x3500"

set "DO_GEO=1"
if "!G!"=="3" set "DO_GEO=0"

echo.
echo ============================================================
echo   确认一下：
if "!CARGS!"=="--color auto"  echo     色彩：自动判断
if "!CARGS!"=="--color gray"  echo     色彩：强制灰度
if "!CARGS!"=="--color color" echo     色彩：强制彩色
echo     尺寸：!SARGS!
if "!DO_GEO!"=="1" echo     后续：裁切 + 地理配准 + 拼接索引
if "!DO_GEO!"=="0" echo     后续：只做裁切（跳过配准）
echo ============================================================
echo.
pause

REM ---------- 第 6 步: 开始处理 ----------
echo.
echo [5/6] 开始处理（幅数多时需要较长时间，请耐心等待）
echo.
echo ------------------------------------------------------------
echo  第 1 关：裁切（纠斜 + 找图廓 + 裁到内容）
echo ------------------------------------------------------------
python scripts\01_crop.py !CARGS! !SARGS!
if errorlevel 1 (
    echo.
    echo   [错误] 裁切过程出错，请把上面的报错内容发给技术人员
    pause
    exit /b 1
)

if "!DO_GEO!"=="0" goto SKIP_GEO

echo.
echo ------------------------------------------------------------
echo  第 2 关：配准（算出每幅图该在的经纬度）
echo ------------------------------------------------------------
python scripts\02_georef.py
if errorlevel 1 (
    echo.
    echo   [错误] 配准失败
    echo.
    echo   最常见的原因：文件名不符合「图号-图名」规则。
    echo   如果你这批图本来就没有图号，请在刚才的 [3/3] 里选 3。
    echo.
    echo   规则说明见 "docs\命名规则与接图表.md"
    pause
    exit /b 1
)

echo.
echo ------------------------------------------------------------
echo  第 3 关：生成拼接索引
echo ------------------------------------------------------------
python scripts\03_build_vrt.py

REM ---------- 自查 ----------
echo.
echo [6/6] 自查 ...
python scripts\03_build_vrt.py >nul 2>&1
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
start "" "work"
echo.
pause
exit /b 0

:SKIP_GEO
echo.
echo ============================================================
echo    裁切完成！
echo.
echo    成果位置：
echo      work\01_crop\   裁切好的图（普通图片，可直接看）
echo.
echo    你选了"只要裁切"，所以跳过了地理配准 ——
echo    这些图没有经纬度，不能与卫星影像叠加分析。
echo.
echo    如果你其实想要经纬度，需要先让文件名带上图号，
echo    或者用 "拼图工作台.bat" 手工拼出图幅之间的位置关系。
echo ============================================================
echo.
start "" "work\01_crop"
echo.
pause
exit /b 0
