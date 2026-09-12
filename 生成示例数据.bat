@echo off
chcp 936 >nul 2>&1
rem 本文件为 GBK 编码, 并把 Python 输出也统一到 GBK, 避免中文乱码
set PYTHONIOENCODING=gbk
cd /d "%~dp0"

echo ============================================================
echo    生成示例数据  -  用于先试试效果
echo ============================================================
echo.
echo   会在 input 文件夹里生成 6 张合成的"假地图"，
echo   用来验证流程能不能跑通。它们不是真实地图数据。
echo.
echo   注意：若 input 里已有你自己的扫描件，
echo         建议先备份，本操作会往里添加文件。
echo.
pause

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 没有找到 Python，请先安装 Python 并勾选 "Add Python to PATH"
    pause
    exit /b 1
)

python scripts\00_make_sample.py
if errorlevel 1 (
    echo.
    echo [错误] 示例生成失败
    pause
    exit /b 1
)

echo.
echo ============================================================
echo    示例已生成。现在可以双击 "一键运行.bat" 看效果。
echo ============================================================
echo.
pause
