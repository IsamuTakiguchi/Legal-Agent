"""検索ソースの共通インターフェース。"""
from __future__ import annotations

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
