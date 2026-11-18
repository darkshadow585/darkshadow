@echo off
title DarkShadow 3D Avatar Bridge Server
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
cd /d %~dp0

echo ========================================================
echo   DarkShadow 3D GPU Fur Avatar Bridge Server
echo   Connecting Three.js Avatar to Windows OS Brain
echo ========================================================
echo.

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" bridge_server.py
) else (
    py -3.11 bridge_server.py 2>nul || py bridge_server.py 2>nul || python bridge_server.py
)

if errorlevel 1 (
    echo.
    echo [ERROR] Bridge server stopped with code %errorlevel%.
)
pause
