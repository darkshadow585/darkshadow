@echo off
title DarkShadow Wake Word Assistant
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
cd /d %~dp0
py -3.11 wake_daemon.py
if errorlevel 1 (
    echo.
    echo [ERROR] Wake daemon band ho gaya error code %errorlevel% ke saath.
    pause
)
