# Stop the Legal-Agent server (Windows).

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

$n = 0
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*legal_agent*serve*" } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    $n++
}
Msg ("Legal-Agent を停止しました（" + $n + " プロセス）。")
exit 0
