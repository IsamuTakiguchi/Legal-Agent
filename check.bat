@echo off
rem Legal-Agent status check (Windows). Double-click.
rem Writes a report to data\status.txt and opens it in Notepad, so nothing is lost even if this window closes.
setlocal
set "HOME_DIR=%LOCALAPPDATA%\Legal-Agent"
if /I not "%~dp0"=="%HOME_DIR%\" (
    if exist "%HOME_DIR%\check.bat" (
        call "%HOME_DIR%\check.bat"
        exit /b
    )
)
cd /d "%~dp0"
if not exist "data" mkdir "data"
set "REPORT=%~dp0data\status.txt"
echo Legal-Agent check started %date% %time% > "%REPORT%"
echo Folder: %~dp0>> "%REPORT%"
echo Home:   %HOME_DIR%>> "%REPORT%"
echo.>> "%REPORT%"
if not exist ".venv\Scripts\python.exe" (
    echo NOT INSTALLED: .venv\Scripts\python.exe is missing in this folder.>> "%REPORT%"
    echo Double-click install.bat first. If you already did, see install.log below.>> "%REPORT%"
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
echo ---- python probe ---->> "%REPORT%"
".venv\Scripts\python.exe" -c "import sys; print(sys.version); print(sys.executable)" >> "%REPORT%" 2>&1
echo python exit code: %errorlevel%>> "%REPORT%"
py -0p >> "%REPORT%" 2>&1
echo.>> "%REPORT%"
".venv\Scripts\python.exe" -m legal_agent doctor --file "%REPORT%" >> "%REPORT%" 2>&1
echo doctor exit code: %errorlevel%>> "%REPORT%"
:show
start "" notepad "%REPORT%"
echo Report written to %REPORT% (opened in Notepad).
pause
endlocal
