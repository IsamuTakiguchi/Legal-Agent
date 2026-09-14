"""ショートカット作成: Windows 以外では何もしない。Windows 分岐は PowerShell 呼び出しをモックして確認。

アイコン（legal_agent/static/legal-agent.ico）は .lnk の IconLocation に渡す。
アイコンの内容が変わったら作り直す（既存の利用者の PC でも次回起動時に差し替わるように）。
"""
import struct
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
    # アイコンを渡している
    assert "-Icon" in calls[0]
    assert Path(calls[0][calls[0].index("-Icon") + 1]).name == "legal-agent.ico"
    assert "$s.IconLocation" in (tmp_path / "data" / "make_shortcut.ps1").read_text(encoding="utf-8")
    # 2 回目は既存を返す（PowerShell を再実行しない）
    assert shortcut.ensure_shortcut(root=tmp_path).startswith("あり:")
    assert len(calls) == 1


def test_icon_change_refreshes_shortcut(monkeypatch, tmp_path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    icon = tmp_path / "legal-agent.ico"
    icon.write_bytes(b"icon-v1")
    monkeypatch.setattr(shortcut, "is_windows", lambda: True)
    monkeypatch.setattr(shortcut, "desktop_dirs", lambda: [desktop])
    monkeypatch.setattr(shortcut, "ICON", icon)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        (desktop / "Legal-Agent.lnk").write_bytes(b"lnk")

        class R:
            returncode = 0
            stderr = ""

        return R()

    monkeypatch.setattr(shortcut.subprocess, "run", fake_run)
    assert shortcut.ensure_shortcut(root=tmp_path).startswith("作成しました:")
    assert len(calls) == 1 and shortcut.is_up_to_date(tmp_path)
    # 中身が同じなら作り直さない
    assert shortcut.ensure_shortcut(root=tmp_path).startswith("あり:")
    assert len(calls) == 1
    # アイコンが変わったら作り直す（既存の .lnk と同じ場所に上書き）
    icon.write_bytes(b"icon-v2")
    assert not shortcut.is_up_to_date(tmp_path)
    msg = shortcut.ensure_shortcut(root=tmp_path)
    assert msg.startswith("アイコンを更新しました:") and len(calls) == 2
    assert calls[1][calls[1].index("-Desktop") + 1] == str(desktop)
    assert shortcut.is_up_to_date(tmp_path)


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


def test_icon_file_is_a_valid_ico():
    """コミットしてあるアイコンが壊れていないこと（改行変換などでの破損検知）。"""
    icon = shortcut.icon_file()
    assert icon is not None and icon.name == "legal-agent.ico"
    data = icon.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1) and count >= 4
    sizes = []
    for i in range(count):
        w, h, _c, _r, _pl, bits, size, off = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
        assert bits == 32 and off + size <= len(data)
        sizes.append(w or 256)
    assert {16, 32, 48, 256} <= set(sizes)
    assert shortcut.icon_signature() and len(shortcut.icon_signature()) == 12
