@echo off
title DARK SHADOW - Living AI Desktop Overlay
chcp 65001 >nul
cd /d %~dp0

echo ===================================================
echo           DARK SHADOW (R) - Windows 11 Overlay
echo ===================================================
echo [1] Launch and Show Immediately (Screen par turant dekhein)
echo [2] Background Mode (Runs quietly; Wake on "Dark Shadow" or Ctrl+Shift+D)
echo [3] Visual Only Mode (No Mic / Sirf particle aur mouse test)
echo ===================================================
set /p choice="Enter choice [1, 2, or 3] (Default: 1): "

if "%choice%"=="2" (
    echo Starting in Background Mode...
    ".venv\Scripts\python.exe" -m dark_shadow.main
) else if "%choice%"=="3" (
    echo Starting in Visual Only Mode...
    ".venv\Scripts\python.exe" -m dark_shadow.main --show --no-voice
) else (
    echo Starting and showing immediately...
    ".venv\Scripts\python.exe" -m dark_shadow.main --show
)

if errorlevel 1 (
    echo.
    echo [ERROR] An error occurred while running DARK SHADOW.
    pause
)
