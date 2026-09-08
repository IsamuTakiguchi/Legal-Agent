@echo off
rem Legal-Agent 導入スクリプト（Windows）。ダブルクリックで実行。
rem  1. Python 3.11+ を探し、無ければ winget で自動インストール
rem  2. 仮想環境を作ってアプリをインストール
rem  3. デスクトップに「Legal-Agent」ショートカットを作成
rem  4. 起動（ブラウザが開き、初回はセットアップ画面が出る）
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

echo === Legal-Agent 導入 ===
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"

if not defined PY (
    echo Python 3.11 以上が見つかりません。winget でインストールします（数分かかります）...
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    rem 新しく入った Python を PATH を更新して再検出
    set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=py -3"
    if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo Python を自動インストールできませんでした。ダウンロードページを開きます。
    echo インストール時に "Add python.exe to PATH" にチェックを入れ、終わったらこのファイルをもう一度ダブルクリックしてください。
    start "" https://www.python.org/downloads/windows/
    pause
    exit /b 1
)
echo Python: %PY%

if not exist ".venv\Scripts\python.exe" (
    echo 仮想環境を作成しています...
    %PY% -m venv .venv || (echo 仮想環境の作成に失敗しました & pause & exit /b 1)
)
echo アプリをインストールしています（初回は数分かかります）...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -e . || (echo インストールに失敗しました & pause & exit /b 1)

rem デスクトップにショートカットを作成
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$d\Legal-Agent.lnk\"); $s.TargetPath='%~dp0start.bat'; $s.WorkingDirectory='%~dp0'; $s.Description='Legal-Agent を起動'; $s.Save()" >nul 2>&1
if exist "%USERPROFILE%\Desktop\Legal-Agent.lnk" echo デスクトップに「Legal-Agent」ショートカットを作りました。

echo.
echo 導入が完了しました。起動します（ブラウザが開きます。初回は API キーと書籍フォルダを画面で設定してください）。
call "%~dp0start.bat"
endlocal
