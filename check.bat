@echo off
rem Legal-Agent status check (Windows). Double-click to see where it is installed and whether it works.
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Not installed yet: .venv not found in %~dp0
    echo Double-click install.bat first.
    if exist install.log (echo --- install.log --- & type install.log)
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m legal_agent doctor
pause
