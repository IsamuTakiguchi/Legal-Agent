@echo off
rem Legal-Agent 起動（Windows）。デスクトップのショートカットからも呼ばれる。
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo まだ導入されていません。install.bat を実行します。
    call "%~dp0install.bat"
    exit /b
)
rem 既に起動していればブラウザだけ開く
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8765/api/status) | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
    start "" http://127.0.0.1:8765/
    exit /b
)
echo 最新版を確認しています...
".venv\Scripts\python.exe" -m legal_agent update
echo Legal-Agent を起動しています。このウィンドウは閉じないでください（最小化して構いません）。
start "Legal-Agent" /min ".venv\Scripts\python.exe" -m legal_agent serve
