@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 (
    py -3 scripts\install_desktop.py
    if errorlevel 1 goto failed
    exit /b 0
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 (
    python scripts\install_desktop.py
    if errorlevel 1 goto failed
    exit /b 0
)
echo Python 3.10 or newer is required.
echo Install Python from https://www.python.org/downloads/windows/ then run this file again.
:failed
echo.
echo Setup did not finish. Read the message above.
pause
exit /b 1
