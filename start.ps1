# Legal-Agent launcher (Windows). Started by start.bat / the desktop shortcut.
# - Applies updates from GitHub; if an update was applied and the server is running, restarts it
# - Starts the server hidden in the background when it is not running, then opens the browser
# Launcher log: Legal-Agent\logs\start-*.log   Server log: Legal-Agent\logs\server-*.log
# (the launcher never writes to the server's own log file: the server keeps it open exclusively)

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
function Test-Server([int]$timeout = 10) {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec $timeout ($Url + "api/status") | Out-Null; return $true } catch { return $false }
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
function Get-ServerProcs {
    return @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*legal_agent*serve*" })
}
function Stop-Server {
    $procs = Get-ServerProcs
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    if ($procs.Count -gt 0) { Start-Sleep -Seconds 3 }
    return $procs.Count
}

# ---- 1. run from AppHome with the private Python ----
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
$LogDir = Join-Path $AppHome "logs"
New-Item -ItemType Directory -Force -Path $LogDir, (Join-Path $AppHome "data") | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Start-Transcript -Path (Join-Path $LogDir ("start-" + $Stamp + ".log")) | Out-Null
Write-Host "=== Legal-Agent start $Stamp ==="
foreach ($pat in @("start-*.log", "server-*.log", "check-*.log")) {
    Get-ChildItem -Path $LogDir -Filter $pat -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -Skip 10 | Remove-Item -Force -ErrorAction SilentlyContinue
}

# ---- 2. shortcut + update (exit 10 = an update was applied) ----
& $Py -m legal_agent shortcut --quiet
Write-Host "[update] Checking GitHub for a newer version ..."
& $Py -m legal_agent update
$updated = ($LASTEXITCODE -eq 10)
Write-Host "[update] exit code $LASTEXITCODE (10 = updated, 0 = up to date, 2 = check failed)"

# ---- 3. is the server already running? ----
$procs = Get-ServerProcs
if ($procs.Count -gt 0) {
    if ($updated) {
        Write-Host "[server] update applied -> restarting the running server so it loads the new version"
        Stop-Server | Out-Null
    } elseif (Test-Server) {
        Write-Host "[server] already running -> opening the browser"
        Stop-Transcript | Out-Null
        Start-Process $Url
        exit 0
    } else {
        Write-Host "[server] process exists but does not answer -> restarting it"
        Stop-Server | Out-Null
    }
}

# ---- 4. start the server with fresh log files ----
$ServerLog = Join-Path $LogDir ("server-" + $Stamp + ".log")
$ServerOut = Join-Path $LogDir ("server-" + $Stamp + "-out.log")
Write-Host "[server] starting (log: $ServerLog)"
Start-Process -FilePath $Py -ArgumentList @("-m", "legal_agent", "serve", "--no-open") -WorkingDirectory $AppHome -WindowStyle Hidden -RedirectStandardOutput $ServerOut -RedirectStandardError $ServerLog
$up = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Server 3) { $up = $true; break }
}
if ($up) {
    Write-Host "[server] up -> $Url"
    Stop-Transcript | Out-Null
    Start-Process $Url
    exit 0
}
Write-Host "[server] did not answer within 60 seconds"
Stop-Transcript | Out-Null
Start-Process notepad.exe $ServerLog
Msg ("Legal-Agent を起動できませんでした。メモ帳で開いたログ（" + $ServerLog + "）の内容を送ってください。")
exit 1
