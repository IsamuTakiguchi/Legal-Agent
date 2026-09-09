@echo off
rem Legal-Agent installer (Windows). Double-click to run.
rem Everything is installed INSIDE this folder (.venv, .env, data). Nothing goes to Program Files.
rem Log: install.log in this folder.
setlocal EnableDelayedExpansion
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
cd /d "%~dp0"
set "LOG=%~dp0install.log"
echo ==== Legal-Agent install %date% %time% ==== >> "%LOG%"
echo === Legal-Agent install ===
echo Folder: %~dp0
echo Log:    %LOG%
echo.

rem Remove "downloaded from the internet" marks so SmartScreen does not block again
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Path '%~dp0' -Recurse -File | Unblock-File" >nul 2>&1

set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"

if not defined PY (
    echo [1/4] Python 3.11+ not found. Installing with winget (this takes a few minutes)...
    echo [1/4] winget install Python >> "%LOG%"
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements >> "%LOG%" 2>&1
    set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=py -3"
    if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python could not be installed automatically. >> "%LOG%"
    echo.
    echo [ERROR] Python could not be installed automatically.
    echo Opening https://www.python.org/downloads/windows/ - run the installer,
    echo check "Add python.exe to PATH", then double-click install.bat again.
    start "" https://www.python.org/downloads/windows/
    pause
    exit /b 1
)
echo [1/4] Python: %PY%
echo [1/4] Python: %PY% >> "%LOG%"

if not exist ".venv\Scripts\python.exe" (
    echo [2/4] Creating virtual environment (.venv)...
    %PY% -m venv .venv >> "%LOG%" 2>&1 || (echo [ERROR] venv failed. See install.log & pause & exit /b 1)
) else (
    echo [2/4] Virtual environment exists (.venv)
)
echo [3/4] Installing the app and its libraries (first time: a few minutes)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip >> "%LOG%" 2>&1
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -e . >> "%LOG%" 2>&1 || (echo [ERROR] pip install failed. See install.log & pause & exit /b 1)
echo [3/4] pip install OK >> "%LOG%"

echo [4/4] Creating desktop shortcut "Legal-Agent"...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$d\Legal-Agent.lnk\"); $s.TargetPath='%~dp0start.bat'; $s.WorkingDirectory='%~dp0'; $s.Description='Start Legal-Agent'; $s.Save()" >> "%LOG%" 2>&1

echo.
".venv\Scripts\python.exe" -m legal_agent doctor --after-install
echo.
echo Starting Legal-Agent now (a browser window will open)...
call "%~dp0start.bat"
echo.
echo Install finished. You can close this window. (Next time: double-click the "Legal-Agent" shortcut on the desktop.)
pause
endlocal
