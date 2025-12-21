@echo off
chcp 65001 >nul
title 自动技能释放工具

:: 检查管理员权限
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
if '%errorlevel%' NEQ '0' (
    echo 正在请求管理员权限...
    goto UACPrompt
) else ( goto gotAdmin )

:UACPrompt
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    echo UAC.ShellExecute "%~s0", "", "", "runas", 1 >> "%temp%\getadmin.vbs"
    "%temp%\getadmin.vbs"
    exit /B

:gotAdmin
    if exist "%temp%\getadmin.vbs" ( del "%temp%\getadmin.vbs" )

echo ====================================
echo     🎮 自动技能释放工具
echo ====================================
echo.

REM 切换到脚本所在目录
cd /d "%~dp0"
echo 当前目录: %CD%
echo.

REM 启动GUI程序
echo 正在启动程序...
echo.
start "" pythonw main.py

REM 检查是否启动成功
if errorlevel 1 (
    echo.
    echo ❌ pythonw启动失败，尝试使用python...
    echo.
    python main.py
    pause
) else (
    echo ✅ 程序已启动！
    echo.
    echo 提示：程序窗口已在后台运行
    echo 关闭此窗口不影响程序运行
    echo.
    timeout /t 2 >nul
)
