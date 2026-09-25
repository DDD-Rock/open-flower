@echo off
setlocal

rem Path to the extracted scrcpy package.
set "SCRCPY_DIR=D:\scrcpy-win64-v4.1"
set "SCRCPY=%SCRCPY_DIR%\scrcpy.exe"
set "ADB=%SCRCPY_DIR%\adb.exe"

rem Add or remove MuMu ADB serials here.
set "SERIALS=emulator-5554 emulator-5556"

if not exist "%SCRCPY%" (
    echo scrcpy.exe was not found:
    echo %SCRCPY%
    echo.
    echo Update SCRCPY_DIR at the top of this file, then try again.
    pause
    exit /b 1
)

if not exist "%ADB%" (
    echo adb.exe was not found:
    echo %ADB%
    echo.
    echo Update SCRCPY_DIR at the top of this file, then try again.
    pause
    exit /b 1
)

echo Connected ADB devices:
"%ADB%" devices
echo.
echo Starting scrcpy instances...

for %%S in (%SERIALS%) do (
    start "MuMu-%%S" "%SCRCPY%" -s "%%S" --no-audio --window-title "MuMu-%%S" --max-size 1280 --video-bit-rate 8M --max-fps 30
)

echo.
echo Started: %SERIALS%
echo Close each scrcpy window to stop its stream.
timeout /t 3 >nul
endlocal
