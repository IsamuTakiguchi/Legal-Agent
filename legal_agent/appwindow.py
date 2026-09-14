"""アプリのウィンドウを開く。

Chrome / Edge の「アプリモード」（--app=URL）で開くと、アドレスバーもタブも無い独立した
ウィンドウになり、タスクバーにも普段のブラウザとは別に並ぶ。ブラウザが見つからないときや
Windows 以外では、従来どおり既定のブラウザで開く（必ずどちらかで開く）。
"""
from __future__ import annotations

import ntpath
import subprocess
import sys
import webbrowser
from pathlib import Path

# 探す順: Chrome を優先し、無ければ Edge
BROWSERS = ("chrome.exe", "msedge.exe")

# App Paths に無い環境のための既知の導入先（%VAR% は展開してから使う）
KNOWN_PATHS: dict[str, tuple[str, ...]] = {
    "chrome.exe": (
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ),
    "msedge.exe": (
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    ),
}


def is_windows() -> bool:
    return sys.platform.startswith("win")


def _from_registry(exe: str) -> Path | None:
    """HKCU→HKLM の App Paths に登録された実行ファイルのパス。"""
    try:
        import winreg
    except ImportError:
        return None
    key = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, key) as k:
                path = Path(str(winreg.QueryValue(k, None)).strip('"'))
            if path.exists():
                return path
        except OSError:
            continue
    return None


def _from_known_paths(exe: str) -> Path | None:
    for pattern in KNOWN_PATHS.get(exe, ()):
        p = Path(ntpath.expandvars(pattern))  # %VAR% は Windows 形式なので ntpath で展開する
        if "%" not in str(p) and p.exists():
            return p
    return None


def find_browser() -> Path | None:
    """アプリウィンドウに使える Chrome（無ければ Edge）を探す。"""
    if not is_windows():
        return None
    for exe in BROWSERS:
        found = _from_registry(exe) or _from_known_paths(exe)
        if found is not None:
            return found
    return None


def app_window_args(exe: Path, url: str, profile: Path) -> list[str]:
    """アプリウィンドウとして開くためのコマンドライン。

    専用プロファイル（--user-data-dir）にするのは、普段使いの Chrome のタブやセッションと
    混ざらないようにするため。閉じても普段の Chrome には影響しない。
    """
    return [
        str(exe),
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1280,860",
    ]


def open_app_window(url: str, profile: Path | None = None, enabled: bool = True, out=print) -> bool:
    """アプリウィンドウで開く。開けたら True、既定のブラウザに後退したら False。"""
    exe = find_browser() if enabled else None
    if exe is not None and profile is not None:
        try:
            profile.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(app_window_args(exe, url, profile), close_fds=True)
            return True
        except Exception as e:  # noqa: BLE001
            out(f"アプリウィンドウを開けませんでした（既定のブラウザで開きます）: {e}")
    try:
        webbrowser.open(url)
    except Exception as e:  # noqa: BLE001
        out(f"ブラウザを開けませんでした: {e}  次を開いてください: {url}")
    return False


def open_for(settings, out=print) -> bool:
    """設定から URL とプロファイルを決めて開く。"""
    url = f"http://{settings.host}:{settings.port}/"
    return open_app_window(url, settings.app_window_dir, enabled=settings.app_window, out=out)
