# Legal-Agent: PowerShell に 1 行貼るだけで導入する入口。
#
#   irm https://raw.githubusercontent.com/IsamuTakiguchi/Legal-Agent/claude/legal-search-agent-app-9xw9z8/get.ps1 | iex
#
# ファイルを保存しないので「Windows によって PC が保護されました」の警告が出ない。
# 中身は ZIP を取ってきて install.ps1 を実行するだけで、導入処理は .exe 版とまったく同じ。

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = "IsamuTakiguchi/Legal-Agent"
$Branch = "claude/legal-search-agent-app-9xw9z8"
$Tmp = Join-Path $env:TEMP ("legal-agent-setup-" + (Get-Date -Format "yyyyMMdd-HHmmss"))

try {
    New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
    $Zip = Join-Path $Tmp "source.zip"
    Write-Host "Legal-Agent をダウンロードしています..."
    Invoke-WebRequest -UseBasicParsing -Uri "https://codeload.github.com/$Repo/zip/refs/heads/$Branch" -OutFile $Zip
    Write-Host "展開しています..."
    Expand-Archive -Path $Zip -DestinationPath $Tmp -Force
    $Src = Get-ChildItem -Path $Tmp -Directory | Select-Object -First 1
    if (-not $Src) { throw "展開したフォルダが見つかりません" }
    $Installer = Join-Path $Src.FullName "install.ps1"
    if (-not (Test-Path $Installer)) { throw "install.ps1 が見つかりません: $Installer" }
    Write-Host "導入を始めます（数分かかります）..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Installer
} catch {
    Write-Host ("失敗しました: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "うまくいかない場合は、リリースページの Legal-Agent-Setup.exe をお試しください:"
    Write-Host "  https://github.com/$Repo/releases/latest"
} finally {
    Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
}
