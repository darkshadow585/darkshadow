@echo off
title DarkShadow Live Voice Assistant
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
cd /d %~dp0

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" main.py 5
) else (
    py -3.11 main.py 5 2>nul || py main.py 5 2>nul || python main.py 5
)

if errorlevel 1 (
    echo.
    echo [ERROR] DarkShadow exited with error code %errorlevel%.
    echo Please check the error above.
)
pause
