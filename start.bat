@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found.
    echo Run install.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" main_v1_3.py
if errorlevel 1 (
    echo.
    echo Application exited with an error.
    pause
)
