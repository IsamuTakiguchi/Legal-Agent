# Legal-Agent installer (Windows PowerShell 5.1+). Started by install.bat.
# - Copies the app to %LOCALAPPDATA%\Legal-Agent (outside OneDrive, short ASCII path)
# - Downloads a private Python into Legal-Agent\python (no system install, no admin rights)
# - Installs the app, creates the desktop shortcut, starts the server, opens the browser
# Everything is logged to Legal-Agent\logs\install-*.log and a message box reports the result.

$ErrorActionPreference = "Continue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$AppHome = Join-Path $env:LOCALAPPDATA "Legal-Agent"
$Here = $PSScriptRoot
$Py = Join-Path $AppHome "python\python.exe"
$Url = "http://127.0.0.1:8765/"
Add-Type -AssemblyName System.Windows.Forms | Out-Null
function Msg([string]$text, [string]$title = "Legal-Agent") {
    [System.Windows.Forms.MessageBox]::Show($text, $title) | Out-Null
}
function Test-Server {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 ($Url + "api/status") | Out-Null; return $true } catch { return $false }
}
function Test-Py {
    if (-not (Test-Path $Py)) { return $false }
    & $Py -c "import sys" 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}
function Invoke-Home([string]$script) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $AppHome $script)
    exit $LASTEXITCODE
}
function Set-PthFile {
    # python3xx._pth: enable "import site" and add ".." (= the app folder) to sys.path
    $pth = Get-ChildItem -Path (Join-Path $AppHome "python") -Filter "python*._pth" | Select-Object -First 1
    if (-not $pth) { throw "python*._pth が見つかりません" }
    $lines = @(Get-Content $pth.FullName | ForEach-Object { if ($_ -match "^#\s*import site") { "import site" } else { $_ } })
    $lines = @($lines | Where-Object { $_ -ne ".." -and $_ -ne "import site" }) + @("..", "import site")
    Set-Content -Path $pth.FullName -Value $lines -Encoding Ascii
}

# ---- 1. relocate to AppHome ----
if ($Here.TrimEnd("\") -ne $AppHome.TrimEnd("\")) {
    New-Item -ItemType Directory -Force -Path $AppHome | Out-Null
    $rc = & robocopy.exe $Here $AppHome /E /XD .venv data .git __pycache__ .pytest_cache python logs /XF install.log .update.json /NFL /NDL /NJH /NJS /NP
    if (-not (Test-Path (Join-Path $AppHome "install.ps1"))) {
        Msg ("アプリを " + $AppHome + " にコピーできませんでした。")
        exit 1
    }
    Invoke-Home "install.ps1"
}

# ---- 2. logging ----
Set-Location $AppHome
$LogDir = Join-Path $AppHome "logs"
New-Item -ItemType Directory -Force -Path $LogDir, (Join-Path $AppHome "data") | Out-Null
$Log = Join-Path $LogDir ("install-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
Start-Transcript -Path $Log | Out-Null
Write-Host "=== Legal-Agent install ==="
Write-Host "Folder: $AppHome"
Write-Host "Log:    $Log"
$Status = Join-Path $AppHome "data\status.txt"
$ok = $false
try {
    Get-ChildItem -Path $AppHome -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue

    # ---- 3. private Python ----
    if (Test-Py) {
        Write-Host "[1/4] Python OK: $Py"
    } else {
        $ver = "3.12.10"
        $PyDir = Join-Path $AppHome "python"
        $zip = Join-Path $env:TEMP "python-$ver-embed-amd64.zip"
        Write-Host "[1/4] Downloading Python $ver (embeddable) ..."
        Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/$ver/python-$ver-embed-amd64.zip" -OutFile $zip
        if (Test-Path $PyDir) { Remove-Item -Recurse -Force $PyDir }
        Expand-Archive -Path $zip -DestinationPath $PyDir -Force
        Set-PthFile
        Write-Host "[1/4] Installing pip ..."
        $getpip = Join-Path $PyDir "get-pip.py"
        Invoke-WebRequest -UseBasicParsing -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getpip
        & $Py $getpip --no-warn-script-location
        if ($LASTEXITCODE -ne 0) { throw "pip のインストールに失敗しました (exit $LASTEXITCODE)" }
        if (-not (Test-Py)) { throw "Python を起動できません: $Py" }
        Write-Host "[1/4] Python ready: $Py"
    }
    # Embedded Python ignores PYTHONPATH, so pip's isolated build environments cannot see
    # setuptools. Put the app folder on sys.path via the ._pth file and build without isolation.
    Set-PthFile
    & $Py -m pip install --disable-pip-version-check -q --no-warn-script-location setuptools wheel
    if ($LASTEXITCODE -ne 0) { throw "setuptools のインストールに失敗しました (pip exit $LASTEXITCODE)" }

    # ---- 4. app + libraries ----
    Write-Host "[2/4] Installing the app and its libraries (first time: a few minutes) ..."
    & $Py -m pip install --disable-pip-version-check -q --no-warn-script-location --no-build-isolation -e $AppHome
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[2/4] Editable install failed (pip exit $LASTEXITCODE); trying a normal install ..."
        & $Py -m pip install --disable-pip-version-check -q --no-warn-script-location --no-build-isolation $AppHome
        if ($LASTEXITCODE -ne 0) { throw "ライブラリのインストールに失敗しました (pip exit $LASTEXITCODE)" }
    }
    & $Py -c "import legal_agent, anthropic, fastapi, pymupdf"
    if ($LASTEXITCODE -ne 0) { throw "インストール後の読み込み確認に失敗しました" }
    Write-Host "[2/4] OK"

    # ---- 5. shortcut ----
    Write-Host "[3/4] Desktop shortcut ..."
    & $Py -m legal_agent shortcut

    # ---- 6. status report ----
    Write-Host "[4/4] Status report ..."
    if (Test-Path $Status) { Remove-Item -Force $Status }
    & $Py -m legal_agent doctor --after-install --file $Status
    $ok = $true
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)"
    Write-Host $_.ScriptStackTrace
}
Stop-Transcript | Out-Null

if (-not $ok) {
    Start-Process notepad.exe $Log
    Msg ("導入の途中で失敗しました。メモ帳で開いたログ（" + $Log + "）の内容を送ってください。")
    exit 1
}
if (Test-Path $Status) { Start-Process notepad.exe $Status }
Msg ("導入が完了しました。`n`n場所: " + $AppHome + "`nデスクトップに「Legal-Agent」ショートカットを作りました。`n`nこの後ブラウザが開き、API キーと書籍フォルダを設定する画面が出ます。")
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $AppHome "start.ps1")
exit 0
