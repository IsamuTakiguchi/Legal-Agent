"""Claude tool_runner を回し、UI 向けイベント（SSE 用 dict）を非同期に流す。"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator

import anthropic

from ..browser.throttle import RunBudget
from ..config import Settings
from ..models import Hit
from ..sources.registry import SourceRegistry
from .citations import resolve_citations
from .context import RunContext, current_run
from .prompts import SYSTEM_PROMPT
from .sessions import ChatSession, SessionStore
from .tools import TOOLS

log = logging.getLogger(__name__)

MAX_PAUSE_RESTARTS = 3


def serialize_block(block: Any) -> dict[str, Any] | None:
    """応答ブロックを次回リクエストで送り返せる dict にする。"""
    t = getattr(block, "type", None)
    if t == "text":
        return {"type": "text", "text": block.text}
    if t == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if t == "thinking":
        d = {"type": "thinking", "thinking": block.thinking or ""}
        if getattr(block, "signature", None):
            d["signature"] = block.signature
        return d
    if t == "redacted_thinking":
        return {"type": "redacted_thinking", "data": block.data}
    if t in ("server_tool_use", "web_search_tool_result", "compaction", "fallback"):
        return block.model_dump(mode="json", exclude_none=True)
    return None


def serialize_content(content: list[Any]) -> list[dict[str, Any]]:
    return [b for b in (serialize_block(x) for x in content) if b]


class AgentRunner:
    def __init__(self, settings: Settings, registry: SourceRegistry, store: SessionStore, client: anthropic.AsyncAnthropic | None = None):
        self.settings = settings
        self.registry = registry
        self.store = store
        self.client = client or anthropic.AsyncAnthropic()

    def _request_params(self) -> dict[str, Any]:
        p: dict[str, Any] = {
            "model": self.settings.model,
            "max_tokens": self.settings.max_tokens,
            "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": self.settings.effort},
            "stream": True,
            "max_iterations": 40,
        }
        if self.settings.fallbacks_enabled and self.settings.model.startswith(("claude-opus-5", "claude-fable")):
            p["betas"] = ["server-side-fallback-2026-07-01"]
            p["fallbacks"] = "default"
        return p

    async def run(self, session: ChatSession, user_text: str, enabled_sources: set[str]) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue()
        ctx = RunContext(
            registry=self.registry,
            budget=RunBudget(self.settings.max_searches_per_source, self.settings.max_fetches_per_run),
            queue=queue,
            enabled_sources=enabled_sources,
            hits={ref: Hit(**d) for ref, d in session.hits.items()},
        )

        async def worker() -> None:
            token = current_run.set(ctx)
            try:
                await self._run_turn(ctx, session, user_text, enabled_sources)
            except anthropic.APIStatusError as e:
                queue.put_nowait({"type": "error", "message": f"Claude API エラー {e.status_code}: {e.message}"})
            except anthropic.APIConnectionError as e:
                queue.put_nowait({"type": "error", "message": f"Claude API に接続できません: {e}"})
            except Exception as e:  # noqa: BLE001
                log.exception("run failed")
                queue.put_nowait({"type": "error", "message": f"{type(e).__name__}: {e}"})
            finally:
                current_run.reset(token)
                queue.put_nowait(None)

        task = asyncio.create_task(worker())
        try:
            while True:
                ev = await queue.get()
                if ev is None:
                    break
                yield ev
        finally:
            if not task.done():
                task.cancel()

    async def _run_turn(self, ctx: RunContext, session: ChatSession, user_text: str, enabled_sources: set[str]) -> None:
        today = time.strftime("%Y-%m-%d")
        src_note = "、".join(sorted(enabled_sources)) or "なし"
        user_content = f"{user_text}\n\n（本日: {today} / 利用可能ソース: {src_note}）"
        messages: list[dict[str, Any]] = list(session.messages) + [{"role": "user", "content": user_content}]
        if not session.title:
            session.title = user_text.strip().splitlines()[0][:40]
        session.turns.append({"role": "user", "text": user_text, "ts": time.time()})

        last_message = None
        restarts = 0
        while True:
            runner = self.client.beta.messages.tool_runner(tools=TOOLS, messages=messages, **self._request_params())
            last_message = None
            async for stream in runner:
                async for ev in stream:
                    et = ev.type
                    if et == "text":
                        ctx.emit({"type": "text_delta", "text": ev.text})
                    elif et == "thinking":
                        if ev.thinking:
                            ctx.emit({"type": "thinking", "text": ev.thinking})
                    elif et == "content_block_stop":
                        blk = ev.content_block
                        if getattr(blk, "type", "") == "tool_use":
                            ctx.emit({"type": "tool_use", "name": blk.name, "input": blk.input})
                        elif getattr(blk, "type", "") == "text":
                            ctx.emit({"type": "text_block_end"})
                msg = await stream.get_final_message()
                last_message = msg
                messages.append({"role": "assistant", "content": serialize_content(msg.content)})
                if msg.stop_reason == "tool_use":
                    resp = await runner.generate_tool_call_response()
                    if resp is not None:
                        messages.append(resp)
            if last_message is None or last_message.stop_reason != "pause_turn":
                break
            restarts += 1
            if restarts > MAX_PAUSE_RESTARTS:
                break

        final_text = ""
        if last_message is not None:
            final_text = "".join(b.text for b in last_message.content if getattr(b, "type", "") == "text")
            if last_message.stop_reason == "refusal":
                detail = getattr(last_message, "stop_details", None)
                why = getattr(detail, "explanation", "") if detail else ""
                final_text = final_text or f"（モデルが応答を拒否しました{': ' + why if why else ''}）"
        text, cites = resolve_citations(final_text, ctx.hits)
        session.hits = {ref: h.to_dict() for ref, h in ctx.hits.items()}
        session.messages = messages
        session.turns.append({"role": "assistant", "text": text, "citations": [c.to_dict() for c in cites], "ts": time.time()})
        self.store.save(session)
        usage = getattr(last_message, "usage", None)
        ctx.emit({
            "type": "done",
            "text": text,
            "citations": [c.to_dict() for c in cites],
            "session_id": session.id,
            "title": session.title,
            "usage": {"input": getattr(usage, "input_tokens", 0), "output": getattr(usage, "output_tokens", 0)} if usage else None,
        })
