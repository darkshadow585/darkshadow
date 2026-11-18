@echo off
echo Stopping all DarkShadow background tasks...
taskkill /f /im python.exe /fi "WINDOWTITLE eq DarkShadow*" 2>nul
taskkill /f /im py.exe 2>nul
echo DarkShadow stopped successfully.
pause
