"""FastAPI サーバ（ローカル専用）。"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .agent.runner import AgentRunner
from .agent.sessions import SessionStore
from .config import Settings, get_settings
from .index.indexer import index_dirs
from .sources.registry import SourceRegistry

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).with_name("static")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    sources: list[str] = Field(default_factory=lambda: ["courts", "tkc", "local", "legal_library"])


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    registry = SourceRegistry(settings)
    store = SessionStore(settings.sessions_dir)
    runner = AgentRunner(settings, registry, store)
    login_tasks: dict[str, asyncio.Task] = {}
    chat_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await registry.aclose()

    app = FastAPI(title="Legal-Agent", lifespan=lifespan)
    app.state.settings = settings
    app.state.registry = registry
    app.state.store = store
    app.state.runner = runner

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        return {
            "model": settings.model,
            "effort": settings.effort,
            "sources": await registry.statuses(),
            "index": registry.local.db.stats(),
            "pdf_dirs": [str(p) for p in settings.pdf_dirs],
            "limits": {
                "max_searches_per_source": settings.max_searches_per_source,
                "max_fetches_per_run": settings.max_fetches_per_run,
            },
        }

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> StreamingResponse:
        session = store.get_or_create(req.session_id)
        enabled = {s for s in req.sources if s in registry.names()}

        async def gen():
            if chat_lock.locked():
                yield _sse({"type": "error", "message": "別の質問を処理中です。完了までお待ちください。"})
                return
            async with chat_lock:
                yield _sse({"type": "start", "session_id": session.id})
                async for ev in runner.run(session, req.message, enabled):
                    yield _sse(ev)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/sessions")
    async def sessions() -> list[dict[str, Any]]:
        return store.list()

    @app.get("/api/sessions/{sid}")
    async def session_detail(sid: str) -> dict[str, Any]:
        s = store.get(sid)
        if s is None:
            raise HTTPException(404, "セッションがありません")
        return {"id": s.id, "title": s.title, "turns": s.turns}

    @app.delete("/api/sessions/{sid}")
    async def session_delete(sid: str) -> dict[str, Any]:
        return {"deleted": store.delete(sid)}

    @app.post("/api/login/{site}")
    async def login(site: str) -> dict[str, Any]:
        if site not in ("tkc", "legal_library"):
            raise HTTPException(404, "ログイン対象は tkc / legal_library です")
        t = login_tasks.get(site)
        if t and not t.done():
            return {"started": False, "message": "ログイン待機中です。開いたブラウザでログインしてください。"}
        cfg = registry.site_config(site)
        login_tasks[site] = asyncio.create_task(registry.browser.wait_for_login(site, cfg))
        return {"started": True, "message": "ブラウザを開きました。ログインしてください（最大 10 分待機）。"}

    @app.get("/api/login/{site}")
    async def login_status(site: str) -> dict[str, Any]:
        t = login_tasks.get(site)
        waiting = bool(t and not t.done())
        result = None
        if t and t.done() and not t.cancelled():
            try:
                result = t.result()
            except Exception as e:  # noqa: BLE001
                result = str(e)
        return {"waiting": waiting, "logged_in": registry.browser.login_state.get(site), "result": result}

    @app.get("/api/books")
    async def books() -> list[dict[str, Any]]:
        return await registry.local.list_books()

    @app.post("/api/index")
    async def reindex(request: Request) -> dict[str, Any]:
        body = {}
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            pass
        rebuild = bool(body.get("rebuild"))
        if not settings.pdf_dirs:
            raise HTTPException(400, "LEGAL_AGENT_PDF_DIRS が設定されていません")
        return await asyncio.to_thread(index_dirs, registry.local.db, settings.pdf_dirs, rebuild, log.info)

    @app.get("/pdf/{doc_id}")
    async def pdf(doc_id: str) -> FileResponse:
        row = registry.local.db.get_document(doc_id)
        if row is None or not Path(row["path"]).exists():
            raise HTTPException(404, "PDF がありません")
        return FileResponse(row["path"], media_type="application/pdf", filename=Path(row["path"]).name, content_disposition_type="inline")

    @app.get("/api/memos")
    async def memos() -> list[dict[str, Any]]:
        out = []
        for p in sorted(settings.memos_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            out.append({"name": p.name, "path": str(p), "updated_at": p.stat().st_mtime})
        return out

    @app.get("/api/memos/{name}")
    async def memo(name: str) -> JSONResponse:
        p = settings.memos_dir / Path(name).name
        if not p.exists():
            raise HTTPException(404)
        return JSONResponse({"name": p.name, "content": p.read_text(encoding="utf-8")})

    return app


def _sse(ev: dict[str, Any]) -> str:
    return "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"
