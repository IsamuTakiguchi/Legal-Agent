"""アプリウィンドウ（Chrome / Edge の --app モード）で開く処理。

Windows 以外で走るので、レジストリと実行ファイルの存在はモックして経路だけを確かめる。
"""
from pathlib import Path

from legal_agent import appwindow


def _fake_paths(existing: set[str]):
    """指定したパスだけが存在する世界にする（本物の Path.exists には委譲しない）。"""
    def exists(self):
        return str(self) in existing

    return exists


def test_find_browser_prefers_chrome_from_registry(monkeypatch):
    monkeypatch.setattr(appwindow, "is_windows", lambda: True)
    found = {"chrome.exe": Path(r"C:\Reg\chrome.exe"), "msedge.exe": Path(r"C:\Reg\msedge.exe")}
    monkeypatch.setattr(appwindow, "_from_registry", lambda exe: found.get(exe))
    monkeypatch.setattr(appwindow, "_from_known_paths", lambda exe: None)
    assert appwindow.find_browser() == Path(r"C:\Reg\chrome.exe")
    # Chrome がレジストリに無ければ Edge に回る
    found.pop("chrome.exe")
    assert appwindow.find_browser() == Path(r"C:\Reg\msedge.exe")


def test_find_browser_falls_back_to_known_paths(monkeypatch):
    monkeypatch.setattr(appwindow, "is_windows", lambda: True)
    monkeypatch.setattr(appwindow, "_from_registry", lambda exe: None)
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\x\AppData\Local")
    monkeypatch.setattr(Path, "exists", _fake_paths({chrome}))
    assert appwindow.find_browser() == Path(chrome)
    # どこにも無ければ None
    monkeypatch.setattr(Path, "exists", _fake_paths(set()))
    assert appwindow.find_browser() is None


def test_find_browser_is_none_off_windows(monkeypatch):
    monkeypatch.setattr(appwindow, "is_windows", lambda: False)
    assert appwindow.find_browser() is None


def test_app_window_args(tmp_path):
    args = appwindow.app_window_args(Path(r"C:\chrome.exe"), "http://127.0.0.1:8765/", tmp_path)
    assert args[0] == r"C:\chrome.exe"
    assert "--app=http://127.0.0.1:8765/" in args
    assert f"--user-data-dir={tmp_path}" in args
    assert "--no-first-run" in args and "--no-default-browser-check" in args


def test_open_app_window_launches_browser(monkeypatch, tmp_path):
    monkeypatch.setattr(appwindow, "find_browser", lambda: Path(r"C:\chrome.exe"))
    launched, opened = [], []
    monkeypatch.setattr(appwindow.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd))
    monkeypatch.setattr(appwindow.webbrowser, "open", lambda url: opened.append(url))
    profile = tmp_path / "app_window"
    assert appwindow.open_app_window("http://x/", profile) is True
    assert opened == [] and launched[0][1] == "--app=http://x/"
    assert profile.is_dir()  # プロファイルの置き場所が作られる


def test_open_app_window_falls_back(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(appwindow.webbrowser, "open", lambda url: opened.append(url))
    # ブラウザが見つからない
    monkeypatch.setattr(appwindow, "find_browser", lambda: None)
    assert appwindow.open_app_window("http://x/", tmp_path) is False
    # 設定で無効
    monkeypatch.setattr(appwindow, "find_browser", lambda: Path(r"C:\chrome.exe"))
    assert appwindow.open_app_window("http://x/", tmp_path, enabled=False) is False
    # 起動に失敗した
    def boom(cmd, **kw):
        raise OSError("cannot start")

    monkeypatch.setattr(appwindow.subprocess, "Popen", boom)
    msgs: list[str] = []
    assert appwindow.open_app_window("http://x/", tmp_path, out=msgs.append) is False
    assert any("既定のブラウザ" in m for m in msgs)
    assert opened == ["http://x/"] * 3


def test_open_for_uses_settings(monkeypatch, settings):
    calls = []
    monkeypatch.setattr(appwindow, "open_app_window",
                        lambda url, profile, enabled=True, out=print: calls.append((url, profile, enabled)) or True)
    assert appwindow.open_for(settings) is True
    url, profile, enabled = calls[0]
    assert url == f"http://{settings.host}:{settings.port}/"
    assert profile == settings.app_window_dir and enabled is True
