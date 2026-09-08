"""検索ソースの共通インターフェース。"""
from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from ..models import Document, Hit, Kind


@runtime_checkable
class Source(Protocol):
    name: str  # "courts" | "tkc" | "local" | "legal_library"
    label: str  # UI 表示名
    kind: Kind  # "case" | "book"
    requires_login: bool

    async def search(self, query: str, limit: int = 20, **filters: Any) -> list[Hit]: ...

    async def fetch(self, item_id: str, **options: Any) -> Document: ...

    async def status(self) -> dict[str, Any]:
        """{"available": bool, "logged_in": bool|None, "detail": str}"""
        ...


def slice_text(text: str, offset: int, max_chars: int) -> tuple[str, int]:
    """本文を offset から max_chars 文字切り出す。戻り値: (部分文字列, 全体長)"""
    offset = max(0, offset)
    return text[offset : offset + max_chars], len(text)


def focus_excerpts(text: str, focus: str, window: int = 800, max_windows: int = 5) -> str:
    """キーワード周辺だけを抜き出す（トークン節約用）。複数語はスペース区切り。"""
    terms = [t for t in re.split(r"\s+", focus.strip()) if t]
    if not terms or not text:
        return ""
    positions: list[int] = []
    for t in terms:
        start = 0
        while len(positions) < max_windows * 4:
            i = text.find(t, start)
            if i < 0:
                break
            positions.append(i)
            start = i + len(t)
    if not positions:
        return ""
    positions.sort()
    half = window // 2
    ranges: list[list[int]] = []
    for p in positions:
        s, e = max(0, p - half), min(len(text), p + half)
        if ranges and s <= ranges[-1][1]:
            ranges[-1][1] = max(ranges[-1][1], e)
        else:
            ranges.append([s, e])
        if len(ranges) >= max_windows and s > ranges[-1][1]:
            break
    ranges = ranges[:max_windows]
    parts = []
    for s, e in ranges:
        parts.append(f"…（{s} 字目〜）\n{text[s:e]}\n…")
    return "\n\n".join(parts)
