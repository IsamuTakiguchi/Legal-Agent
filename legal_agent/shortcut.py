"""デスクトップショートカット（Windows）の作成と確認。

install.bat の一行 PowerShell は引用符の扱いで環境によって失敗するため、
Python 側から PowerShell スクリプトファイル（引用符問題なし）を実行し、失敗時は VBScript にフォールバックする。
start.bat / check.bat / doctor から呼ばれ、無ければ毎回作り直す（自己修復）。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHORTCUT_NAME = "Legal-Agent.lnk"
ICON = Path(__file__).with_name("static") / "legal-agent.ico"
# .lnk の作り方（アイコン以外）を変えたら上げる。既存の PC でも作り直される
LNK_VERSION = "2"


def icon_file() -> Path | None:
    """ショートカットに設定するアイコン（無ければ None＝既定のアイコンのまま）。"""
    return ICON if ICON.exists() else None


def icon_signature() -> str:
    """アイコンの内容と .lnk の作り方の署名。変わったらショートカットを作り直す合図にする。"""
    icon = icon_file()
    if icon is None:
        return f"v{LNK_VERSION}"
    try:
        return f"{hashlib.sha1(icon.read_bytes()).hexdigest()[:12]}-v{LNK_VERSION}"
    except OSError:
        return f"v{LNK_VERSION}"


def _state_file(root: Path) -> Path:
    return Path(root) / "data" / ".shortcut.json"


def _saved_signature(root: Path) -> str:
    try:
        return str(json.loads(_state_file(root).read_text(encoding="utf-8")).get("icon", ""))
    except Exception:  # noqa: BLE001
        return ""


def _save_signature(root: Path, sig: str, lnk: Path) -> None:
    try:
        f = _state_file(root)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"icon": sig, "lnk": str(lnk)}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def is_up_to_date(root: Path = ROOT) -> bool:
    """ショートカットがあり、アイコンも今のものと一致しているか。"""
    return find_shortcut() is not None and _saved_signature(root) == icon_signature()


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
param([string]$Desktop, [string]$Target, [string]$WorkDir, [string]$Icon)
$path = Join-Path $Desktop "Legal-Agent.lnk"
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($path)
$s.TargetPath = $Target
$s.WorkingDirectory = $WorkDir
$s.Description = "Legal-Agent"
$s.WindowStyle = 7
if ($Icon) { $s.IconLocation = "$Icon,0" }
$s.Save()
if (-not (Test-Path $path)) { exit 1 }
"""

_VBS = r"""
Set sh = CreateObject("WScript.Shell")
Set lnk = sh.CreateShortcut(WScript.Arguments(0) & "\Legal-Agent.lnk")
lnk.TargetPath = WScript.Arguments(1)
lnk.WorkingDirectory = WScript.Arguments(2)
lnk.Description = "Legal-Agent"
lnk.WindowStyle = 7
If WScript.Arguments.Count > 3 Then lnk.IconLocation = WScript.Arguments(3) & ",0"
lnk.Save
"""


def create_desktop_shortcut(root: Path = ROOT, out=print, force: bool = False) -> Path | None:
    """ショートカットを作成（アイコンが変わっていれば作り直し）して Path を返す。Windows 以外や失敗時は None。"""
    if not is_windows():
        return None
    sig = icon_signature()
    existing = find_shortcut()
    if existing and not force and _saved_signature(root) == sig:
        return existing
    # 既にあるなら同じ場所に上書きし、無ければデスクトップの第一候補に作る
    desktop = existing.parent if existing else None
    if desktop is None:
        dirs = desktop_dirs()
        if not dirs:
            out("デスクトップのフォルダが見つかりませんでした")
            return None
        desktop = dirs[0]
    target = str(root / "start.bat")
    icon = icon_file()
    tmp = root / "data"
    tmp.mkdir(parents=True, exist_ok=True)
    ps1 = tmp / "make_shortcut.ps1"
    ps1.write_text(_PS1, encoding="utf-8")
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
           "-Desktop", str(desktop), "-Target", target, "-WorkDir", str(root)]
    if icon is not None:
        cmd += ["-Icon", str(icon)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            out(f"PowerShell でのショートカット作成に失敗: {r.stderr.strip()[:300]}")
    except Exception as e:  # noqa: BLE001
        out(f"PowerShell を実行できません: {e}")
    p = desktop / SHORTCUT_NAME
    if p.exists():
        _save_signature(root, sig, p)
        return p
    vbs = tmp / "make_shortcut.vbs"
    vbs.write_text(_VBS, encoding="utf-8")
    args = ["cscript", "//nologo", str(vbs), str(desktop), target, str(root)]
    if icon is not None:
        args.append(str(icon))
    try:
        subprocess.run(args, capture_output=True, text=True, timeout=60)
    except Exception as e:  # noqa: BLE001
        out(f"cscript を実行できません: {e}")
    if p.exists():
        _save_signature(root, sig, p)
        return p
    return None


def ensure_shortcut(out=print, quiet: bool = False, root: Path = ROOT) -> str:
    """状態を表す文字列を返す（doctor 用）。アイコンが変わっていれば作り直す。"""
    if not is_windows():
        return "（Windows 以外では作成しません）"
    before = find_shortcut()
    if before and _saved_signature(root) == icon_signature():
        return f"あり: {before}"
    p = create_desktop_shortcut(root=root, out=out if not quiet else (lambda s: None))
    if p:
        return f"アイコンを更新しました: {p}" if before else f"作成しました: {p}"
    return "作成できませんでした（start.bat をダブルクリックして起動できます）"
