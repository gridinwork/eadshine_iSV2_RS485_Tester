@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo Leadshine iSV2 RS485 Tester - INSTALL
echo ============================================

where py >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python launcher "py" not found.
    echo Install Python 3.11 or 3.12 from python.org and enable PATH.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo DONE. Run start.bat
pause
