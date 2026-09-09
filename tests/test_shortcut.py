"""ショートカット作成: Windows 以外では何もしない。Windows 分岐は PowerShell 呼び出しをモックして確認。"""
from pathlib import Path

from legal_agent import shortcut


def test_non_windows_noop(monkeypatch):
    monkeypatch.setattr(shortcut, "is_windows", lambda: False)
    assert shortcut.create_desktop_shortcut() is None
    assert "Windows 以外" in shortcut.ensure_shortcut()


def test_windows_creates_via_powershell(monkeypatch, tmp_path):
    desktop = tmp_path / "OneDrive" / "Desktop"
    desktop.mkdir(parents=True)
    monkeypatch.setattr(shortcut, "is_windows", lambda: True)
    monkeypatch.setattr(shortcut, "desktop_dirs", lambda: [desktop])
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "powershell":
            (desktop / "Legal-Agent.lnk").write_bytes(b"lnk")

            class R:
                returncode = 0
                stderr = ""

            return R()
        raise AssertionError("cscript should not be needed")

    monkeypatch.setattr(shortcut.subprocess, "run", fake_run)
    p = shortcut.create_desktop_shortcut(root=tmp_path, out=lambda s: None)
    assert p == desktop / "Legal-Agent.lnk"
    assert calls[0][:5] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    assert Path(calls[0][5]).name == "make_shortcut.ps1" and "-Target" in calls[0]
    # 2 回目は既存を返す
    assert shortcut.ensure_shortcut().startswith("あり:")


def test_windows_falls_back_to_vbs(monkeypatch, tmp_path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(shortcut, "is_windows", lambda: True)
    monkeypatch.setattr(shortcut, "desktop_dirs", lambda: [desktop])

    def fake_run(cmd, **kw):
        if cmd[0] == "powershell":
            class R:
                returncode = 1
                stderr = "blocked"

            return R()
        (desktop / "Legal-Agent.lnk").write_bytes(b"lnk")

        class R2:
            returncode = 0
            stderr = ""

        return R2()

    monkeypatch.setattr(shortcut.subprocess, "run", fake_run)
    msgs: list[str] = []
    assert shortcut.create_desktop_shortcut(root=tmp_path, out=msgs.append) == desktop / "Legal-Agent.lnk"
    assert any("PowerShell" in m for m in msgs)
