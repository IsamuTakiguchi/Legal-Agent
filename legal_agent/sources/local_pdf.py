"""手持ち書籍 PDF（ローカル索引）ソース。"""
from __future__ import annotations

import asyncio
from typing import Any

from ..config import Settings
from ..index.db import IndexDB, make_snippet
from ..models import Document, Hit


class LocalPDFSource:
    name = "local"
    label = "手持ち書籍PDF"
    kind = "book"
    requires_login = False

    def __init__(self, settings: Settings, db: IndexDB | None = None):
        self.settings = settings
        self.db = db or IndexDB(settings.db_path)

    @staticmethod
    def make_ref(doc_id: str, page_no: int) -> str:
        return f"local:{doc_id}:p{page_no}"

    @staticmethod
    def parse_ref(item_id: str) -> tuple[str, int | None]:
        """'abc123' / 'abc123:p45' / 'local:abc123:p45' → (doc_id, page)"""
        parts = item_id.split(":")
        if parts and parts[0] == "local":
            parts = parts[1:]
        doc_id = parts[0]
        page = None
        if len(parts) > 1 and parts[1].startswith("p") and parts[1][1:].isdigit():
            page = int(parts[1][1:])
        return doc_id, page

    def _url(self, doc_id: str, page_no: int) -> str:
        return f"/pdf/{doc_id}#page={page_no}"

    async def search(self, query: str, limit: int = 20, **filters: Any) -> list[Hit]:
        doc_id = filters.get("book_id")
        rows = await asyncio.to_thread(self.db.search, query, limit, doc_id)
        hits = []
        for r in rows:
            hits.append(
                Hit(
                    ref=self.make_ref(r.doc_id, r.page_no),
                    source=self.name,
                    kind="book",
                    title=r.title,
                    subtitle=f"{r.author} / p.{r.page_no}" if r.author else f"p.{r.page_no}",
                    snippet=make_snippet(r.text, query),
                    url=self._url(r.doc_id, r.page_no),
                    meta={"book_id": r.doc_id, "page": r.page_no, "author": r.author, "path": r.path},
                )
            )
        return hits

    async def fetch(self, item_id: str, **options: Any) -> Document:
        doc_id, page = self.parse_ref(item_id)
        page = int(options.get("page") or page or 1)
        span = int(options.get("span", 1))
        doc = await asyncio.to_thread(self.db.get_document, doc_id)
        if doc is None:
            raise KeyError(f"書籍 ID {doc_id} は索引にありません。search_books の結果の book_id を使ってください。")
        rows = await asyncio.to_thread(self.db.get_pages, doc_id, page, span)
        chunks = [f"――― p.{r['page_no']} ―――\n{r['text'].strip()}" for r in rows]
        text = "\n\n".join(chunks)
        return Document(
            ref=self.make_ref(doc_id, page),
            source=self.name,
            kind="book",
            title=doc["title"],
            text=text,
            url=self._url(doc_id, page),
            meta={"著者": doc["author"], "総ページ": doc["page_count"], "ページ": f"{page}（前後 {span}）"},
            offset=0,
            total_chars=len(text),
        )

    async def status(self) -> dict[str, Any]:
        st = await asyncio.to_thread(self.db.stats)
        return {
            "available": st["documents"] > 0,
            "logged_in": None,
            "detail": f"{st['documents']} 冊 / {st['pages']} ページ",
        }

    async def list_books(self) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(self.db.list_documents)
        return [dict(r) for r in rows]
