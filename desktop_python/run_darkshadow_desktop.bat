@echo off
title DarkShadow Desktop AI — Option B (WebGL2 + Python)
echo ==========================================================
echo   DarkShadow Desktop AI (PySide6 WebGL2 + 5 Upgrades)
echo ==========================================================
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [!] Created .env from .env.example — paste your GEMINI_API_KEY in .env!
    )
)
if not exist ".venv" (
    echo Creating Python 3.11 virtual environment...
    py -3.11 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
echo Installing Windows desktop dependencies...
python -m pip install --upgrade pip
pip install -r windows_requirements.txt
echo.
echo Launching DarkShadow Transparent WebGL2 Desktop Overlay...
echo Say "Hey Dark Shadow" or right-click the System Tray icon!
python darkshadow_desktop.py
pause
