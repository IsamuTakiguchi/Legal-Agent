# Legal-Agent status check (Windows). Writes data\status.txt and opens it in Notepad.

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
    if (Test-Path (Join-Path $AppHome "check.ps1")) { Invoke-Home "check.ps1" }
}
$DataDir = Join-Path $AppHome "data"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$Report = Join-Path $DataDir "status.txt"
$head = @()
$head += "Legal-Agent check " + (Get-Date)
$head += "Folder (script): " + $Here
$head += "App home:        " + $AppHome
$head += "Python:          " + $Py + "  exists=" + (Test-Path $Py)
$head += ""
Set-Content -Path $Report -Value $head -Encoding UTF8
if (-not (Test-Py)) {
    Add-Content -Path $Report -Value "NOT INSTALLED (private Python missing or broken). Double-click install.bat."
    Add-Content -Path $Report -Value ""
    Add-Content -Path $Report -Value "Files in app home:"
    Get-ChildItem -Path $AppHome -ErrorAction SilentlyContinue | ForEach-Object { Add-Content -Path $Report -Value ("  " + $_.Name) }
    $logs = Get-ChildItem -Path (Join-Path $AppHome "logs") -Filter "install-*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 1
    if ($logs) {
        Add-Content -Path $Report -Value ""
        Add-Content -Path $Report -Value ("---- " + $logs.Name + " ----")
        Get-Content $logs.FullName | Add-Content -Path $Report
    }
} else {
    Set-Location $AppHome
    New-Item -ItemType Directory -Force -Path (Join-Path $AppHome "logs") | Out-Null
    Start-Transcript -Path (Join-Path $AppHome ("logs\check-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")) | Out-Null
    & $Py -m legal_agent doctor --file $Report
    Stop-Transcript | Out-Null
}
Start-Process notepad.exe $Report
exit 0
