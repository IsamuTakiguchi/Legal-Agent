"""ブラウザ上のセットアップ（/api/setup）: API キー未設定の検出、フォルダ一覧、保存→索引開始。"""
import time
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

import legal_agent.app as app_module
import legal_agent.onedrive as od
from legal_agent.app import create_app
from legal_agent.config import Settings


def _make_books(root: Path) -> None:
    for name in ("労働法講義", "民法入門"):
        p = root / "書籍" / f"{name}.pdf"
        p.parent.mkdir(parents=True, exist_ok=True)
        d = pymupdf.open()
        d.new_page().insert_text((72, 72), f"{name} contract law")
        d.save(str(p))
        d.close()


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """API キー無し・.env 無しの状態でアプリを作る。"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("LEGAL_AGENT_PDF_DIRS", raising=False)
    monkeypatch.setattr("legal_agent.config.sdk_has_credentials", lambda: False)
    onedrive = tmp_path / "OneDrive"
    _make_books(onedrive)
    monkeypatch.setattr(od, "detect_onedrive_roots", lambda: [onedrive])
    env_path = tmp_path / ".env"
    s = Settings(_env_file=None, data_dir=tmp_path / "data", headless=True, min_interval_sec=0, env_path=env_path)
    s.ensure_dirs()
    app = create_app(s)
    with TestClient(app) as c:
        yield c, s, onedrive, env_path


def test_needs_setup_blocks_chat_and_lists_folders(fresh):
    c, s, onedrive, env_path = fresh
    assert s.needs_setup is True
    assert c.get("/api/status").json()["needs_setup"] is True
    assert c.post("/api/chat", json={"message": "x"}).status_code == 400
    f = c.get("/api/setup/folders").json()
    assert f["onedrive_roots"] == [str(onedrive)]
    assert f["folders"] == [{"path": str(onedrive / "書籍"), "pdfs": 2, "root": str(onedrive)}]


def test_setup_rejects_bad_key(fresh, monkeypatch):
    c, s, onedrive, env_path = fresh

    async def bad(key, timeout=15.0):
        return "API キーが正しくありません（認証エラー）"

    monkeypatch.setattr(app_module, "validate_api_key", bad)
    r = c.post("/api/setup", json={"api_key": "sk-bad", "pdf_dirs": []})
    assert r.status_code == 400 and "認証エラー" in r.json()["detail"]
    assert not env_path.exists()
    assert c.post("/api/setup", json={"api_key": "", "pdf_dirs": []}).status_code == 400


def test_setup_saves_and_indexes(fresh, monkeypatch):
    c, s, onedrive, env_path = fresh

    async def ok(key, timeout=15.0):
        return None

    monkeypatch.setattr(app_module, "validate_api_key", ok)
    r = c.post("/api/setup", json={"api_key": "sk-ant-test", "pdf_dirs": [str(onedrive / "書籍")], "manual_path": f'"{onedrive / "missing"}"'})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["needs_setup"] is False and j["chromium"] is False
    assert j["missing"] == [str(onedrive / "missing")]
    env = env_path.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-ant-test" in env and f"LEGAL_AGENT_PDF_DIRS={onedrive / '書籍'},{onedrive / 'missing'}" in env
    assert s.anthropic_api_key == "sk-ant-test" and s.pdf_dirs[0] == onedrive / "書籍"
    # 索引がバックグラウンドで走り、冊数が増える
    for _ in range(50):
        st = c.get("/api/status").json()
        if st["index"]["documents"] == 2 and not st["indexing"]:
            break
        time.sleep(0.2)
    assert st["needs_setup"] is False and st["index"]["documents"] == 2
    assert st["pdf_dirs_status"][1]["exists"] is False
    # 2 回目はキー無しでもフォルダだけ更新できる
    r = c.post("/api/setup", json={"api_key": "", "pdf_dirs": [str(onedrive / "書籍")]})
    assert r.status_code == 200 and "sk-ant-test" in env_path.read_text(encoding="utf-8")
