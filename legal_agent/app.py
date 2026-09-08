"""FastAPI サーバ（ローカル専用）。起動時に索引更新とログイン確認を自動で行う。"""
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
from . import onedrive
from .onedrive import describe_dir, list_pdf_folders, strip_quotes
from .setup_wizard import apply_setup, login_sites_enabled, validate_api_key
from .sources.registry import SourceRegistry

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).with_name("static")
LOGIN_SITES = ("tkc", "legal_library")
INDEX_RESCAN_SEC = 3600


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    sources: list[str] = Field(default_factory=lambda: ["courts", "tkc", "local", "legal_library"])


class AutoconfRequest(BaseModel):
    query: str = "解雇"


class SetupRequest(BaseModel):
    api_key: str | None = None
    pdf_dirs: list[str] = Field(default_factory=list)
    manual_path: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    registry = SourceRegistry(settings)
    store = SessionStore(settings.sessions_dir)
    runner = AgentRunner(settings, registry, store)
    login_tasks: dict[str, asyncio.Task] = {}
    autoconf_tasks: dict[str, asyncio.Task] = {}
    chat_lock = asyncio.Lock()
    bg: dict[str, Any] = {"indexing": False, "index_result": None, "startup_login": {}}
    bg_tasks: list[asyncio.Task] = []
    index_wake = asyncio.Event()  # セットアップ完了時などに即時再スキャンさせる

    async def auto_index_loop() -> None:
        while True:
            if settings.pdf_dirs:
                bg["indexing"] = True
                try:
                    bg["index_result"] = await asyncio.to_thread(index_dirs, registry.local.db, settings.pdf_dirs, False, log.info)
                except Exception as e:  # noqa: BLE001
                    bg["index_result"] = {"error": str(e)}
                finally:
                    bg["indexing"] = False
            index_wake.clear()
            try:
                await asyncio.wait_for(index_wake.wait(), timeout=INDEX_RESCAN_SEC)
            except asyncio.TimeoutError:
                pass

    async def startup_login() -> None:
        for site in registry.login_sites():
            user, password = settings.credentials(site)
            if not (user and password):
                continue
            try:
                cfg = registry.site_config(site)
                ok = await registry.browser.ensure_logged_in(site, cfg, user, password)
                bg["startup_login"][site] = ok
            except Exception as e:  # noqa: BLE001
                bg["startup_login"][site] = False
                registry.browser.last_error[site] = str(e)
                log.warning("%s: 起動時ログインに失敗: %s", site, e)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_index:
            bg_tasks.append(asyncio.create_task(auto_index_loop()))
        if settings.auto_login:
            bg_tasks.append(asyncio.create_task(startup_login()))
        yield
        for t in bg_tasks:
            t.cancel()
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
            "needs_setup": settings.needs_setup,
            "model": settings.model,
            "effort": settings.effort,
            "sources": await registry.statuses(),
            "index": registry.local.db.stats(),
            "indexing": bg["indexing"],
            "index_result": bg["index_result"],
            "pdf_dirs": [str(p) for p in settings.pdf_dirs],
            "pdf_dirs_status": await asyncio.to_thread(lambda: [describe_dir(p) for p in settings.pdf_dirs]),
            "auto_configure": settings.auto_configure,
            "limits": {
                "max_searches_per_source": settings.max_searches_per_source,
                "max_fetches_per_run": settings.max_fetches_per_run,
            },
        }

    # ---- ブラウザ上のセットアップ ----
    @app.get("/api/setup/folders")
    async def setup_folders() -> dict[str, Any]:
        def scan() -> dict[str, Any]:
            roots = onedrive.detect_onedrive_roots()  # モジュール経由で参照（テストで差し替え可能）
            folders = []
            for r in roots:
                for p, n in list_pdf_folders(r):
                    folders.append({"path": str(p), "pdfs": n, "root": str(r)})
            return {"onedrive_roots": [str(r) for r in roots], "folders": folders, "current": [str(p) for p in settings.pdf_dirs]}

        return await asyncio.to_thread(scan)

    @app.post("/api/setup")
    async def setup(req: SetupRequest) -> dict[str, Any]:
        api_key = (req.api_key or "").strip()
        if api_key:
            err = await validate_api_key(api_key)
            if err:
                raise HTTPException(400, err)
        elif settings.needs_setup:
            raise HTTPException(400, "API キーを入力してください")
        dirs = [strip_quotes(p) for p in (req.pdf_dirs or []) if strip_quotes(p)]
        if req.manual_path and strip_quotes(req.manual_path):
            dirs.append(strip_quotes(req.manual_path))
        env = await asyncio.to_thread(apply_setup, api_key or None, dirs, settings.env_path)
        if api_key:
            settings.anthropic_api_key = api_key
            runner.reset_client()
        settings.pdf_dirs = [Path(p).expanduser() for p in dirs]
        settings.export_api_key()
        index_wake.set()
        missing = [p for p in dirs if not Path(p).expanduser().is_dir()]
        return {"ok": True, "pdf_dirs": dirs, "missing": missing, "needs_setup": settings.needs_setup, "env_path": str(settings.env_path), "chromium": login_sites_enabled(env)}

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> StreamingResponse:
        if settings.needs_setup:
            raise HTTPException(400, "初回セットアップ（API キーの設定）が必要です")
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

    # ---- ログイン ----
    def _check_site(site: str) -> None:
        if site not in LOGIN_SITES:
            raise HTTPException(404, "対象は tkc / legal_library です")
        if site not in registry.login_sites():
            raise HTTPException(400, f"{site} は保留中で、アプリからはアクセスしません（README の「利用規約の確認結果」参照）")

    @app.post("/api/login/{site}")
    async def login(site: str, request: Request) -> dict[str, Any]:
        _check_site(site)
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            pass
        manual = bool(body.get("manual"))
        t = login_tasks.get(site)
        if t and not t.done():
            return {"started": False, "message": "ログイン処理中です。"}
        cfg = registry.site_config(site)
        user, password = settings.credentials(site)
        if user and password and not manual:
            registry.browser.login_state.pop(site, None)
            login_tasks[site] = asyncio.create_task(registry.browser.ensure_logged_in(site, cfg, user, password))
            return {"started": True, "mode": "auto", "message": "保存された認証情報で自動ログインしています…"}
        login_tasks[site] = asyncio.create_task(registry.browser.wait_for_login(site, cfg))
        return {"started": True, "mode": "manual", "message": "ブラウザを開きました。ログインしてください（最大 10 分待機）。"}

    @app.get("/api/login/{site}")
    async def login_status(site: str) -> dict[str, Any]:
        _check_site(site)
        t = login_tasks.get(site)
        waiting = bool(t and not t.done())
        result = None
        if t and t.done() and not t.cancelled():
            try:
                result = t.result()
            except Exception as e:  # noqa: BLE001
                result = str(e)
        return {
            "waiting": waiting,
            "logged_in": registry.browser.login_state.get(site),
            "result": result,
            "error": registry.browser.last_error.get(site),
        }

    # ---- セレクタ自動発見 ----
    @app.post("/api/autoconf/{site}")
    async def autoconf(site: str, req: AutoconfRequest) -> dict[str, Any]:
        _check_site(site)
        t = autoconf_tasks.get(site)
        if t and not t.done():
            return {"started": False, "message": "自動設定を実行中です。"}
        src = registry.get(site)
        autoconf_tasks[site] = asyncio.create_task(src.autoconfigure(req.query))
        return {"started": True, "message": "Claude が画面構造を解析しています（1〜3 分）。"}

    @app.get("/api/autoconf/{site}")
    async def autoconf_status(site: str) -> dict[str, Any]:
        _check_site(site)
        t = autoconf_tasks.get(site)
        st = dict(registry.get(site).autoconf_state)
        st["waiting"] = bool(t and not t.done())
        return st

    # ---- 書籍・索引 ----
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
        bg["indexing"] = True
        try:
            return await asyncio.to_thread(index_dirs, registry.local.db, settings.pdf_dirs, rebuild, log.info)
        finally:
            bg["indexing"] = False

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
