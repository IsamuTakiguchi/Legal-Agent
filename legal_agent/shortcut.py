"""デスクトップショートカット（Windows）の作成と確認。

install.bat の一行 PowerShell は引用符の扱いで環境によって失敗するため、
Python 側から PowerShell スクリプトファイル（引用符問題なし）を実行し、失敗時は VBScript にフォールバックする。
start.bat / check.bat / doctor から呼ばれ、無ければ毎回作り直す（自己修復）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHORTCUT_NAME = "Legal-Agent.lnk"


def is_windows() -> bool:
    return sys.platform.startswith("win")


def desktop_dirs() -> list[Path]:
    """デスクトップの候補（OneDrive でリダイレクトされている場合を含む）。存在するものだけ返す。"""
    cands: list[Path] = []
    if is_windows():
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                capture_output=True, text=True, timeout=20,
            )
            if r.returncode == 0 and r.stdout.strip():
                cands.append(Path(r.stdout.strip()))
        except Exception:  # noqa: BLE001
            pass
    home = Path.home()
    for key in ("OneDriveConsumer", "OneDrive"):
        if os.environ.get(key):
            cands.append(Path(os.environ[key]) / "Desktop")
            cands.append(Path(os.environ[key]) / "デスクトップ")
    cands.append(home / "Desktop")
    out: list[Path] = []
    seen: set[str] = set()
    for c in cands:
        k = str(c).lower()
        if k not in seen and c.is_dir():
            seen.add(k)
            out.append(c)
    return out


def find_shortcut() -> Path | None:
    for d in desktop_dirs():
        p = d / SHORTCUT_NAME
        if p.exists():
            return p
    return None


_PS1 = r"""
param([string]$Desktop, [string]$Target, [string]$WorkDir)
$path = Join-Path $Desktop "Legal-Agent.lnk"
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($path)
$s.TargetPath = $Target
$s.WorkingDirectory = $WorkDir
$s.Description = "Legal-Agent"
$s.Save()
if (-not (Test-Path $path)) { exit 1 }
"""

_VBS = r"""
Set sh = CreateObject("WScript.Shell")
Set lnk = sh.CreateShortcut(WScript.Arguments(0) & "\Legal-Agent.lnk")
lnk.TargetPath = WScript.Arguments(1)
lnk.WorkingDirectory = WScript.Arguments(2)
lnk.Description = "Legal-Agent"
lnk.Save
"""


def create_desktop_shortcut(root: Path = ROOT, out=print) -> Path | None:
    """ショートカットを作成して Path を返す。Windows 以外や失敗時は None。"""
    if not is_windows():
        return None
    existing = find_shortcut()
    if existing:
        return existing
    dirs = desktop_dirs()
    if not dirs:
        out("デスクトップのフォルダが見つかりませんでした")
        return None
    desktop = dirs[0]
    target = str(root / "start.bat")
    tmp = root / "data"
    tmp.mkdir(parents=True, exist_ok=True)
    ps1 = tmp / "make_shortcut.ps1"
    ps1.write_text(_PS1, encoding="utf-8")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1), "-Desktop", str(desktop), "-Target", target, "-WorkDir", str(root)],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            out(f"PowerShell でのショートカット作成に失敗: {r.stderr.strip()[:300]}")
    except Exception as e:  # noqa: BLE001
        out(f"PowerShell を実行できません: {e}")
    p = desktop / SHORTCUT_NAME
    if p.exists():
        return p
    vbs = tmp / "make_shortcut.vbs"
    vbs.write_text(_VBS, encoding="utf-8")
    try:
        subprocess.run(["cscript", "//nologo", str(vbs), str(desktop), target, str(root)], capture_output=True, text=True, timeout=60)
    except Exception as e:  # noqa: BLE001
        out(f"cscript を実行できません: {e}")
    return p if p.exists() else None


def ensure_shortcut(out=print, quiet: bool = False) -> str:
    """状態を表す文字列を返す（doctor 用）。"""
    if not is_windows():
        return "（Windows 以外では作成しません）"
    p = find_shortcut()
    if p:
        return f"あり: {p}"
    p = create_desktop_shortcut(out=out if not quiet else (lambda s: None))
    if p:
        return f"作成しました: {p}"
    return "作成できませんでした（start.bat をダブルクリックして起動できます）"
