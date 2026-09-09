@echo off
rem Legal-Agent status check (Windows). Double-click.
rem Writes a report to data\status.txt and opens it in Notepad, so nothing is lost even if this window closes.
setlocal
cd /d "%~dp0"
if not exist "data" mkdir "data"
set "REPORT=%~dp0data\status.txt"
echo Legal-Agent check started %date% %time% > "%REPORT%"
echo Folder: %~dp0>> "%REPORT%"
echo.>> "%REPORT%"
if not exist ".venv\Scripts\python.exe" (
    echo NOT INSTALLED: .venv\Scripts\python.exe is missing in this folder.>> "%REPORT%"
    echo Double-click install.bat first. If you already did, open install.log (also in this folder).>> "%REPORT%"
    echo.>> "%REPORT%"
    echo Files in this folder:>> "%REPORT%"
    dir /b >> "%REPORT%"
    if exist "install.log" (
        echo.>> "%REPORT%"
        echo ---- install.log ---->> "%REPORT%"
        type "install.log" >> "%REPORT%"
    )
    goto show
)
set "PYTHONUTF8=1"
".venv\Scripts\python.exe" -m legal_agent doctor --file "%REPORT%" >> "%REPORT%" 2>&1
:show
start "" notepad "%REPORT%"
echo Report written to %REPORT% (opened in Notepad).
pause
endlocal
