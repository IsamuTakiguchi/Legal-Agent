"""保留中のソース。サイトには一切アクセスせず、利用者が自分で検索するための案内だけを返す。

TKC ローライブラリーと LEGAL LIBRARY は、利用規約の確認（docs/TERMS_REVIEW.md）を踏まえて既定で保留にしている。
再有効化は .env の LEGAL_AGENT_TKC_ENABLED / LEGAL_AGENT_LEGAL_LIBRARY_ENABLED を true にする。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..models import Document, Hit, Kind


class OnHoldSource:
    requires_login = False

    def __init__(self, name: str, label: str, kind: Kind, url_template: str, note: str):
        self.name = name
        self.label = label
        self.kind = kind
        self.url_template = url_template  # {query} を含んでよい
        self.note = note

    def search_url(self, query: str) -> str:
        return self.url_template.replace("{query}", quote(query))

    async def search(self, query: str, limit: int = 20, **filters: Any) -> list[Hit]:
        return [
            Hit(
                ref=f"{self.name}:manual:{quote(query)}",
                source=self.name,
                kind=self.kind,
                title=f"{self.label.split('（')[0]} で「{query}」を利用者自身が検索する",
                subtitle="このソースは保留中のため、アプリからはアクセスしません。リンクを開いて手動で検索してください",
                snippet=self.note,
                url=self.search_url(query),
                meta={"manual": True, "query": query},
            )
        ]

    async def fetch(self, item_id: str, **options: Any) -> Document:
        raise KeyError(self.note + " 本文は利用者がブラウザで確認します。")

    async def status(self) -> dict[str, Any]:
        return {"available": False, "logged_in": None, "detail": "保留中（手動検索の案内のみ）", "manual_only": True}


TKC_NOTE = "TKC ローライブラリーは保留中です（利用規約 9-1 の複製・目的外利用との関係と個別規約が未確認のため。docs/TERMS_REVIEW.md 参照）。"
LEGAL_LIBRARY_NOTE = "LEGAL LIBRARY は利用規約第 8 条（自動化手段によるアクセス・AI 等の使用の禁止）により、アプリからはアクセスしません。"


def tkc_on_hold() -> OnHoldSource:
    return OnHoldSource("tkc", "TKCローライブラリー（保留中）", "case", "https://www.lawlibrary.jp/Law/LoginForm.aspx", TKC_NOTE)


def legal_library_on_hold() -> OnHoldSource:
    return OnHoldSource("legal_library", "LEGAL LIBRARY（保留中）", "book", "https://legal-library.jp/search?keyword={query}", LEGAL_LIBRARY_NOTE)
