@echo off
rem Legal-Agent installer (Windows). Double-click to run.
rem The app is installed to %LOCALAPPDATA%\Legal-Agent (outside OneDrive; short ASCII path).
rem Log: install.log in that folder. A status report opens in Notepad at the end.
setlocal
set "HOME_DIR=%LOCALAPPDATA%\Legal-Agent"
cd /d "%~dp0"
if /I not "%~dp0"=="%HOME_DIR%\" (
    echo Copying the app to %HOME_DIR% ...
    echo (OneDrive folders and long Japanese paths break the Python environment, so the app lives there.)
    if not exist "%HOME_DIR%" mkdir "%HOME_DIR%"
    robocopy "%~dp0." "%HOME_DIR%" /E /XD .venv data .git __pycache__ .pytest_cache /XF install.log .update.json /NFL /NDL /NJH /NJS /NP >nul
    if not exist "%HOME_DIR%\install.bat" (
        echo [ERROR] Could not copy the app to %HOME_DIR%
        pause
        exit /b 1
    )
    call "%HOME_DIR%\install.bat"
    exit /b
)
set "LOG=%~dp0install.log"
set "PYTHONUTF8=1"
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
    echo [1/4] Python 3.11+ not found. Installing with winget - this takes a few minutes...
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
    start "" notepad "%LOG%"
    pause
    exit /b 1
)
echo [1/4] Python: %PY%
echo [1/4] Python: %PY% >> "%LOG%"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1 || (
        echo [2/4] Existing .venv is broken. Recreating...
        rmdir /s /q ".venv"
    )
)
if not exist ".venv\Scripts\python.exe" (
    echo [2/4] Creating virtual environment .venv ...
    %PY% -m venv .venv >> "%LOG%" 2>&1 || (echo [ERROR] venv failed. See install.log & start "" notepad "%LOG%" & pause & exit /b 1)
) else (
    echo [2/4] Virtual environment exists: .venv
)
echo [3/4] Installing the app and its libraries - first time: a few minutes...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip >> "%LOG%" 2>&1
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -e . >> "%LOG%" 2>&1 || (echo [ERROR] pip install failed. See install.log & start "" notepad "%LOG%" & pause & exit /b 1)
echo [3/4] pip install OK >> "%LOG%"

echo [4/4] Creating desktop shortcut "Legal-Agent"...
".venv\Scripts\python.exe" -m legal_agent shortcut >> "%LOG%" 2>&1

if not exist "data" mkdir "data"
".venv\Scripts\python.exe" -m legal_agent doctor --after-install --file "%~dp0data\status.txt" >> "%LOG%" 2>&1
start "" notepad "%~dp0data\status.txt"
echo.
echo Install finished. A status report was opened in Notepad.
echo Starting Legal-Agent now - a browser window will open...
call "%~dp0start.bat"
echo.
echo You can close this window. Next time: double-click the "Legal-Agent" shortcut on the desktop.
pause
endlocal
