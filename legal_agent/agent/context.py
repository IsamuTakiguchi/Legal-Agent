"""1 回の質問（run）に紐づく実行コンテキスト。ツールはここ経由でソース・予算・イベント送出にアクセスする。"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from ..browser.throttle import RunBudget
from ..models import Hit
from ..sources.registry import SourceRegistry


@dataclass
class RunContext:
    registry: SourceRegistry
    budget: RunBudget
    queue: asyncio.Queue
    enabled_sources: set[str]
    hits: dict[str, Hit] = field(default_factory=dict)

    def emit(self, event: dict[str, Any]) -> None:
        self.queue.put_nowait(event)

    def register(self, hits: list[Hit]) -> None:
        for h in hits:
            self.hits[h.ref] = h


current_run: ContextVar[RunContext] = ContextVar("current_run")
