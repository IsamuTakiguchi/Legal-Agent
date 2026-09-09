@echo off
rem Legal-Agent launcher (Windows). Also used by the desktop shortcut.
rem Server log: data\server.log
setlocal
cd /d "%~dp0"
if not exist "data" mkdir "data"
echo start.bat %date% %time% > "data\last_start.txt"
set "PYTHONUTF8=1"
if not exist ".venv\Scripts\python.exe" (
    echo Not installed yet. Running install.bat ...
    call "%~dp0install.bat"
    exit /b
)
rem Already running? Then just open the browser.
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8765/api/status) | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
    echo Legal-Agent is already running. Opening http://127.0.0.1:8765/
    start "" http://127.0.0.1:8765/
    exit /b
)
".venv\Scripts\python.exe" -m legal_agent shortcut --quiet >> "data\server.log" 2>&1
echo Checking for updates...
".venv\Scripts\python.exe" -m legal_agent update >> "data\server.log" 2>&1
echo Starting server (log: data\server.log)...
start "Legal-Agent server" /min cmd /c "".venv\Scripts\python.exe" -m legal_agent serve --no-open >> "data\server.log" 2>&1"
set /a TRIES=0
:wait
set /a TRIES+=1
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8765/api/status) | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 goto up
if %TRIES% geq 40 goto failed
timeout /t 1 /nobreak >nul
goto wait
:up
echo Legal-Agent is running: http://127.0.0.1:8765/
start "" http://127.0.0.1:8765/
exit /b 0
:failed
echo [ERROR] The server did not start within 40 seconds. Opening data\server.log ...
start "" notepad "data\server.log"
echo Double-click check.bat for a full status report.
pause
exit /b 1
