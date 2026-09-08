"""LEGAL LIBRARY（法律書籍サブスク）。

利用規約（令和 8 年 3 月 18 日改定）第 8 条は、
  - 「自動化された手段（情報収集ボット、クローラー、スクレイパーなど）を使用して、本サービスに…アクセスしたりする行為」
  - 「利用者様自身又は第三者の AI 等（…ツール、システム、モデル…）の使用、開発、学習、テスト、検証等をする行為」
  - 「当社が認める方法以外の方法で入力・出力・複製等をする行為」
を禁じている。本アプリのブラウザ自動操作と Claude への本文送信はこれに該当しうるため、既定では
`LegalLibraryLinkSource`（サイトへ一切アクセスせず、利用者が自分で検索するためのリンクを返すだけ）を使う。

運営会社から許諾を得た場合のみ `LEGAL_AGENT_LEGAL_LIBRARY_ENABLED=true` で `LegalLibrarySource`（ブラウザ操作）に切り替わる。
設定は selectors.yaml の legal_library: 節。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..browser.session import BrowserSession
from ..config import Settings
from ..models import Document, Hit
from .browser_site import BrowserSiteSource

TERMS_NOTE = "LEGAL LIBRARY 利用規約第 8 条（自動化手段によるアクセス・AI 等の使用の禁止）により、アプリからはアクセスしません。"


class LegalLibrarySource(BrowserSiteSource):
    def __init__(self, settings: Settings, browser: BrowserSession):
        super().__init__("legal_library", "book", settings, browser)


class LegalLibraryLinkSource:
    """サイトにアクセスしない代替。利用者が自分で LEGAL LIBRARY を検索するための案内だけを返す。"""

    name = "legal_library"
    label = "LEGAL LIBRARY（手動検索の案内のみ）"
    kind = "book"
    requires_login = False

    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def search_url(query: str) -> str:
        return f"https://legal-library.jp/search?keyword={quote(query)}"

    async def search(self, query: str, limit: int = 20, **filters: Any) -> list[Hit]:
        return [
            Hit(
                ref=f"legal_library:manual:{quote(query)}",
                source=self.name,
                kind="book",
                title=f"LEGAL LIBRARY で「{query}」を利用者自身が検索する",
                subtitle="アプリからの自動アクセスは規約で禁止されているため、リンクを開いて手動で検索してください",
                snippet=TERMS_NOTE,
                url=self.search_url(query),
                meta={"manual": True, "query": query},
            )
        ]

    async def fetch(self, item_id: str, **options: Any) -> Document:
        raise KeyError(TERMS_NOTE + " 本文は利用者がブラウザで確認します。")

    async def status(self) -> dict[str, Any]:
        return {"available": False, "logged_in": None, "detail": "規約により自動アクセス不可（手動検索の案内のみ）", "manual_only": True}
