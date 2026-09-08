"""セットアップウィザードの PDF フォルダ選択（OneDrive 検出→番号選択→手入力フォールバック）。"""
from pathlib import Path

from legal_agent import setup_wizard


def _make_tree(root: Path) -> None:
    for rel in ("書籍/労働法/a.pdf", "書籍/労働法/b.pdf", "書籍/民法/c.pdf"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4")


def test_choose_by_number(tmp_path, monkeypatch):
    root = tmp_path / "OneDrive"
    _make_tree(root)
    monkeypatch.setattr(setup_wizard, "_ask", lambda *a, **k: "1")
    import legal_agent.onedrive as od

    monkeypatch.setattr(od, "detect_onedrive_roots", lambda: [root])
    out: list[str] = []
    res = setup_wizard.choose_pdf_dirs("", ask=lambda *a, **k: "1", out=out.append)
    assert res == str(root / "書籍")
    assert any("PDF 3 件" in line for line in out)


def test_choose_multiple_and_manual(tmp_path, monkeypatch):
    root = tmp_path / "OneDrive"
    _make_tree(root)
    import legal_agent.onedrive as od

    monkeypatch.setattr(od, "detect_onedrive_roots", lambda: [root])
    res = setup_wizard.choose_pdf_dirs("", ask=lambda *a, **k: "2, 3", out=lambda s: None)
    assert set(res.split(",")) == {str(root / "書籍" / "労働法"), str(root / "書籍" / "民法")}
    # 番号ではなくパスを直接入力
    manual = tmp_path / "other"
    manual.mkdir()
    res = setup_wizard.choose_pdf_dirs("", ask=lambda *a, **k: f'"{manual}"', out=lambda s: None)
    assert res == str(manual)


def test_no_onedrive_falls_back_to_manual(tmp_path, monkeypatch):
    import legal_agent.onedrive as od

    monkeypatch.setattr(od, "detect_onedrive_roots", lambda: [])
    prompts: list[str] = []
    missing = tmp_path / "nope"
    out: list[str] = []
    res = setup_wizard.choose_pdf_dirs("", ask=lambda prompt, default="", **k: (prompts.append(prompt), str(missing))[1], out=out.append)
    assert res == str(missing) and "パスで入力" in prompts[0]
    assert any("見つかりません" in line for line in out)
