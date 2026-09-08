"""ツール層のテスト。RunContext をスタブ・レジストリで組み立てて直接呼ぶ。"""
import asyncio

import pytest

pytestmark = pytest.mark.anyio

from legal_agent.agent.context import RunContext, current_run
from legal_agent.agent.tools import TOOLS, get_book_pages, get_case, search_books, search_cases
from legal_agent.browser.throttle import RunBudget
from legal_agent.index.db import IndexDB
from legal_agent.models import Document, Hit, LoginRequired
from legal_agent.sources.local_pdf import LocalPDFSource


class StubCases:
    name, label, kind, requires_login = "courts", "裁判所", "case", False

    async def search(self, query, limit=20, **f):
        return [Hit(ref="courts:9", source="courts", kind="case", title=f"{query} 事件", subtitle="最高裁", meta={"total": 1})]

    async def fetch(self, item_id, **o):
        return Document(ref=f"courts:{item_id}", source="courts", kind="case", title="判決", text="本文" * 10, total_chars=20)


class StubLogin:
    name, label, kind, requires_login = "tkc", "TKC", "case", True

    async def search(self, query, limit=20, **f):
        raise LoginRequired("tkc")

    async def fetch(self, item_id, **o):
        raise LoginRequired("tkc")


class StubRegistry:
    def __init__(self, settings, local):
        self.settings = settings
        self._m = {"courts": StubCases(), "tkc": StubLogin(), "local": local}

    def get(self, n):
        return self._m[n]


@pytest.fixture
def ctx(settings, tmp_path):
    db = IndexDB(tmp_path / "i.sqlite3")
    db.add_document("bk", "/b.pdf", "労働法", "著者", "", 1, 1, [(1, "解雇の要件"), (2, "解雇権濫用法理")])
    local = LocalPDFSource(settings, db)
    c = RunContext(registry=StubRegistry(settings, local), budget=RunBudget(2, 2), queue=asyncio.Queue(), enabled_sources={"courts", "tkc", "local"})
    token = current_run.set(c)
    yield c
    current_run.reset(token)


def _events(ctx):
    out = []
    while not ctx.queue.empty():
        out.append(ctx.queue.get_nowait())
    return out


def test_schema_names():
    assert [t.name for t in TOOLS] == ["search_cases", "get_case", "search_books", "get_book_pages", "save_memo"]
    schema = search_cases.to_dict()["input_schema"]
    assert schema["required"] == ["query"]


async def test_search_cases_and_login_required(ctx):
    out = await search_cases.call({"query": "解雇", "sources": ["courts", "tkc"]})
    assert "[ref=courts:9] 解雇 事件" in out
    assert "要ログイン" in out and "TKC ログイン" in out
    assert "courts:9" in ctx.hits
    types = [e["type"] for e in _events(ctx)]
    assert types[0] == "tool_call" and "login_required" in types and "tool_result" in types


async def test_budget_limits(ctx):
    await search_cases.call({"query": "a", "sources": ["courts"]})
    await search_cases.call({"query": "b", "sources": ["courts"]})
    out = await search_cases.call({"query": "c", "sources": ["courts"]})
    assert "上限" in out
    await get_case.call({"source": "courts", "case_id": "9"})
    await get_case.call({"source": "courts", "case_id": "9"})
    assert "上限" in await get_case.call({"source": "courts", "case_id": "9"})


async def test_disabled_source(ctx):
    ctx.enabled_sources = {"local"}
    assert "有効な判例ソースがありません" in await search_cases.call({"query": "x"})


async def test_books(ctx):
    out = await search_books.call({"query": "解雇", "sources": ["local"]})
    assert "[ref=local:bk:p1]" in out and "[ref=local:bk:p2]" in out
    out = await get_book_pages.call({"source": "local", "book_id": "bk", "page": 2, "span": 0})
    assert "解雇権濫用法理" in out and "――― p.1" not in out
    assert "エラー" in await get_book_pages.call({"source": "local", "book_id": "nope"})
    assert "source は" in await get_book_pages.call({"source": "courts", "book_id": "x"})
