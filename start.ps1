# Legal-Agent launcher (Windows). Started by start.bat / the desktop shortcut.

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

if ($Here.TrimEnd("\") -ne $AppHome.TrimEnd("\")) {
    if (Test-Path (Join-Path $AppHome "start.ps1")) { Invoke-Home "start.ps1" }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Here "install.ps1")
    exit $LASTEXITCODE
}
if (-not (Test-Py)) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $AppHome "install.ps1")
    exit $LASTEXITCODE
}
Set-Location $AppHome
$DataDir = Join-Path $AppHome "data"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$ServerLog = Join-Path $DataDir "server.log"
$ServerOut = Join-Path $DataDir "server.out.log"
if (Test-Server) {
    Start-Process $Url
    exit 0
}
"start " + (Get-Date) | Add-Content -Path (Join-Path $DataDir "last_start.txt")
& $Py -m legal_agent shortcut --quiet *>> $ServerLog
& $Py -m legal_agent update *>> $ServerLog
Start-Process -FilePath $Py -ArgumentList @("-m", "legal_agent", "serve", "--no-open") -WorkingDirectory $AppHome -WindowStyle Hidden -RedirectStandardOutput $ServerOut -RedirectStandardError $ServerLog
$up = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Server) { $up = $true; break }
}
if ($up) {
    Start-Process $Url
    exit 0
}
Start-Process notepad.exe $ServerLog
Msg ("Legal-Agent を起動できませんでした。メモ帳で開いたログ（" + $ServerLog + "）の内容を送ってください。")
exit 1
