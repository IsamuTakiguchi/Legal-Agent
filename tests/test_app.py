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
    assert st["sources"]["tkc"]["requires_login"] is True
    assert st["index"]["documents"] == 0
    assert c.get("/api/sessions").json() == []
    assert c.get("/api/sessions/none").status_code == 404
    assert c.get("/pdf/none").status_code == 404
    assert c.post("/api/login/other").status_code == 404
    assert c.get("/api/login/tkc").json() == {"waiting": False, "logged_in": None, "result": None, "error": None}
    assert c.post("/api/autoconf/other", json={}).status_code == 404
    # LEGAL LIBRARY は既定で規約によりアクセスしない → ログイン・自動設定は 400
    assert c.get("/api/autoconf/legal_library").status_code == 400
    assert c.post("/api/login/legal_library").status_code == 400
    assert st["sources"]["legal_library"]["available"] is False and st["sources"]["legal_library"]["requires_login"] is False
    ac = c.get("/api/autoconf/tkc").json()
    assert ac["waiting"] is False and ac["running"] is False
    assert st["sources"]["tkc"]["auto_login"] is False and st["sources"]["tkc"]["configured"] is False
    assert st["indexing"] is False and st["auto_configure"] is True
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
