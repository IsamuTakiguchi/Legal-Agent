import json

import pytest
from fastapi.testclient import TestClient

from legal_agent.app import create_app


@pytest.fixture
def client(settings, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    app = create_app(settings)
    with TestClient(app) as c:
        yield c, app


def test_status_and_sessions(client):
    c, app = client
    st = c.get("/api/status").json()
    assert st["model"] == "claude-opus-5"
    assert set(st["sources"]) == {"courts", "tkc", "local", "legal_library"}
    assert st["index"]["documents"] == 0
    assert c.get("/api/sessions").json() == []
    assert c.get("/api/sessions/none").status_code == 404
    assert c.get("/pdf/none").status_code == 404
    assert c.post("/api/login/other").status_code == 404
    assert c.post("/api/autoconf/other", json={}).status_code == 404
    # TKC / LEGAL LIBRARY は既定で保留 → ログイン・自動設定は 400
    for site in ("tkc", "legal_library"):
        assert c.get(f"/api/autoconf/{site}").status_code == 400
        assert c.post(f"/api/login/{site}").status_code == 400
        assert st["sources"][site]["available"] is False and st["sources"][site]["requires_login"] is False
        assert "保留" in st["sources"][site]["detail"]
    assert st["indexing"] is False and st["auto_configure"] is True
    assert st["pending_downloads"] == 0 and st["auto_download_cloud_pdfs"] is False
    assert c.get("/api/downloads").json() == {"pending": [], "allow_all": False, "auto": False}
    r = c.post("/api/downloads/allow", json={"paths": ["C:/x/a.pdf"], "all": True}).json()
    assert r["allowed"] == 1 and r["allow_all"] is True and app.state.approvals.is_allowed("C:/x/a.pdf")
    assert st["usage_month"]["cost_usd"] == 0 and st["usage_month"]["over_budget"] is False and st["usage_month"]["calls"] == 0
    u = c.get("/api/usage").json()
    assert u["month"] == st["usage_month"]["month"] and u["months"][0]["calls"] == 0 and u["usd_jpy"] == 150.0
    assert "platform.claude.com" in u["console_url"] and "概算" in u["note"]
    # 記録すると status / usage に反映される
    from types import SimpleNamespace
    app.state.runner.ledger.record(SimpleNamespace(input_tokens=1_000_000, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0), "claude-opus-5")
    assert c.get("/api/status").json()["usage_month"]["cost_usd"] == 5.0
    assert c.get("/api/usage?months=1").json()["this_month"]["by_model"]["claude-opus-5"]["calls"] == 1
    assert c.get("/").status_code == 200 and "Legal-Agent" in c.get("/").text


def test_chat_stream_with_stubbed_runner(client):
    c, app = client

    async def fake_run(session, text, enabled):
        assert enabled == {"courts", "local"}
        yield {"type": "text_delta", "text": "こんにちは"}
        yield {"type": "done", "text": "こんにちは", "citations": [], "session_id": session.id, "title": "t"}

    app.state.runner.run = fake_run
    with c.stream("POST", "/api/chat", json={"message": "hi", "sources": ["courts", "local", "bogus"]}) as r:
        assert r.status_code == 200
        events = [json.loads(l[6:]) for l in r.iter_lines() if l.startswith("data: ")]
    assert [e["type"] for e in events] == ["start", "text_delta", "done"]
    sid = events[0]["session_id"]
    assert c.get(f"/api/sessions/{sid}").status_code == 200
    assert c.delete(f"/api/sessions/{sid}").json() == {"deleted": True}


def test_status_uses_cached_dir_scan(settings, monkeypatch, tmp_path):
    """/api/status は OneDrive フォルダを毎回走査せず、索引のたびに更新されるキャッシュを返す（start.ps1 の稼働判定が 2 秒で切れないように）。"""
    from legal_agent import app as app_module

    books = tmp_path / "books"
    books.mkdir()
    settings.pdf_dirs = [books]
    settings.auto_index = False
    calls = []
    real = app_module.describe_dir
    monkeypatch.setattr(app_module, "describe_dir", lambda p: calls.append(p) or real(p))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with TestClient(create_app(settings)) as c:
        st = c.get("/api/status").json()
        assert st["pdf_dirs_status"][0]["path"] == str(books) and st["pending_downloads"] == 0
        c.get("/api/status")
        assert len(calls) == 1  # 2 回目はキャッシュ
        assert c.post("/api/index", json={}).status_code == 200
        assert len(calls) == 2  # 索引後に再計算
        c.get("/api/downloads")
        assert len(calls) == 3  # 許可画面を開いたときは最新を取り直す
