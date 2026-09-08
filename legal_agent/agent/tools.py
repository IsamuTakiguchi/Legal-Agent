"""Claude に公開するツール群（@beta_async_tool）。"""
from __future__ import annotations

from typing import Any

from anthropic import beta_async_tool

from ..browser.throttle import BudgetExceeded
from ..memo.export import save_memo as _save_memo
from ..models import Document, Hit, LoginRequired
from ..sources.registry import BOOK_SOURCES, CASE_SOURCES
from .context import RunContext, current_run

LOGIN_HINT = {
    "tkc": "TKCローライブラリーは未ログインです。利用者に画面右上の「TKC ログイン」ボタンからログインしてもらってください。ログイン後に再検索できます。",
    "legal_library": "LEGAL LIBRARY は未ログインです。利用者に画面右上の「LEGAL LIBRARY ログイン」ボタンからログインしてもらってください。",
}


def _ctx() -> RunContext:
    return current_run.get()


def _pick_sources(requested: list[str] | None, allowed: tuple[str, ...], ctx: RunContext) -> list[str]:
    wanted = [s for s in (requested or list(allowed)) if s in allowed]
    enabled = [s for s in wanted if s in ctx.enabled_sources]
    return enabled


def _format_hits(source_label: str, hits: list[Hit], total: int | None) -> str:
    head = f"■ {source_label}: {len(hits)} 件" + (f"（全 {total} 件中）" if total else "")
    if not hits:
        return head + "\n  該当なし"
    return head + "\n" + "\n".join("- " + h.to_tool_text() for h in hits)


async def _run_search(ctx: RunContext, name: str, query: str, limit: int, **filters: Any) -> str:
    src = ctx.registry.get(name)
    try:
        ctx.budget.take_search(name)
        ctx.emit({"type": "tool_progress", "message": f"{src.label} を検索中: {query}"})
        hits = await src.search(query, limit=limit, **filters)
        ctx.register(hits)
        ctx.emit({"type": "tool_result", "source": name, "count": len(hits), "hits": [h.to_dict() for h in hits]})
        total = hits[0].meta.get("total") if hits else None
        return _format_hits(src.label, hits, total)
    except LoginRequired as e:
        ctx.emit({"type": "login_required", "site": e.site})
        return f"■ {src.label}: 要ログイン。{LOGIN_HINT.get(e.site, str(e))}"
    except BudgetExceeded as e:
        return f"■ {src.label}: {e}"
    except Exception as e:  # noqa: BLE001
        return f"■ {src.label}: エラー（{type(e).__name__}: {e}）"


async def _run_fetch(ctx: RunContext, name: str, item_id: str, **options: Any) -> str:
    src = ctx.registry.get(name)
    try:
        ctx.budget.take_fetch()
        ctx.emit({"type": "tool_progress", "message": f"{src.label} の本文を取得中: {item_id}"})
        doc: Document = await src.fetch(item_id, **options)
        hit = ctx.hits.get(doc.ref)
        if hit is None:
            hit = Hit(ref=doc.ref, source=name, kind=doc.kind, title=doc.title, subtitle="", url=doc.url, meta=dict(doc.meta))
            ctx.register([hit])
        ctx.emit({"type": "tool_result", "source": name, "count": 1, "hits": [hit.to_dict()], "fetched": True})
        return doc.to_tool_text()
    except LoginRequired as e:
        ctx.emit({"type": "login_required", "site": e.site})
        return f"要ログイン。{LOGIN_HINT.get(e.site, str(e))}"
    except BudgetExceeded as e:
        return str(e)
    except KeyError as e:
        return f"エラー: {e.args[0] if e.args else e}"
    except Exception as e:  # noqa: BLE001
        return f"エラー（{type(e).__name__}: {e}）"


@beta_async_tool
async def search_cases(
    query: str,
    sources: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    court: str | None = None,
    limit: int = 10,
) -> str:
    """裁判例（判例）を検索する。結果の各行に [ref=...] が付くので、引用時はその ref を使う。

    Args:
        query: 全文検索キーワード。スペース区切りで複数語（OR 検索）。法律用語・条文番号・事件名などを簡潔に。
        sources: 検索するソース。"courts"（裁判所サイト・公開）、"tkc"（TKCローライブラリー）。省略時は有効な全ソース。
        date_from: 裁判年月日の下限（YYYY-MM-DD または YYYY）。
        date_to: 裁判年月日の上限（YYYY-MM-DD または YYYY）。
        court: 裁判所名で絞る（例: "最高裁判所", "東京高等裁判所", "大阪地方裁判所"）。
        limit: 各ソースから返す最大件数（1〜20）。
    """
    ctx = _ctx()
    limit = max(1, min(int(limit), 20))
    names = _pick_sources(sources, CASE_SOURCES, ctx)
    if not names:
        return "有効な判例ソースがありません（利用者がソースを無効化しています）。"
    ctx.emit({"type": "tool_call", "name": "search_cases", "input": {"query": query, "sources": names, "date_from": date_from, "date_to": date_to, "court": court}})
    parts = []
    for n in names:
        parts.append(await _run_search(ctx, n, query, limit, date_from=date_from, date_to=date_to, court=court))
    return "\n\n".join(parts)


@beta_async_tool
async def get_case(source: str, case_id: str, offset: int = 0) -> str:
    """裁判例の詳細情報と判決本文を取得する。長い判決は offset を進めて続きを読む。

    Args:
        source: "courts" または "tkc"。
        case_id: search_cases の結果の ref から source: を除いた ID（例: ref=courts:96174 なら "96174"）。
        offset: 本文の読み始め位置（文字数）。前回の応答に示された続きの位置を指定する。
    """
    ctx = _ctx()
    if source not in CASE_SOURCES:
        return f"source は {', '.join(CASE_SOURCES)} のいずれかです。"
    ctx.emit({"type": "tool_call", "name": "get_case", "input": {"source": source, "case_id": case_id, "offset": offset}})
    return await _run_fetch(ctx, source, case_id, offset=offset)


@beta_async_tool
async def search_books(query: str, sources: list[str] | None = None, book_id: str | None = None, limit: int = 10) -> str:
    """法律書籍・文献を検索する。手持ち書籍PDFはページ単位でヒットし、[ref=local:<book_id>:p<ページ>] が付く。

    Args:
        query: 検索語。スペース区切りで複数語（AND 検索）。2 文字以上の語を推奨。
        sources: "local"（手持ち書籍PDF）、"legal_library"（LEGAL LIBRARY）。省略時は有効な全ソース。
        book_id: 手持ち書籍PDFの特定の 1 冊に絞る場合、その book_id。
        limit: 各ソースから返す最大件数（1〜20）。
    """
    ctx = _ctx()
    limit = max(1, min(int(limit), 20))
    names = _pick_sources(sources, BOOK_SOURCES, ctx)
    if not names:
        return "有効な文献ソースがありません（利用者がソースを無効化しています）。"
    ctx.emit({"type": "tool_call", "name": "search_books", "input": {"query": query, "sources": names, "book_id": book_id}})
    parts = []
    for n in names:
        filters = {"book_id": book_id} if (n == "local" and book_id) else {}
        parts.append(await _run_search(ctx, n, query, limit, **filters))
    return "\n\n".join(parts)


@beta_async_tool
async def get_book_pages(source: str, book_id: str, page: int = 1, span: int = 1, offset: int = 0) -> str:
    """書籍の該当ページ本文を読む。手持ち書籍PDFは指定ページの前後 span ページをまとめて返す。

    Args:
        source: "local" または "legal_library"。
        book_id: search_books の結果の book_id（local）または ref から source: を除いた ID（legal_library）。
        page: 読みたいページ番号（local のみ有効）。
        span: 前後に含めるページ数（0〜3。local のみ有効）。
        offset: 本文の読み始め位置（legal_library の長文用）。
    """
    ctx = _ctx()
    if source not in BOOK_SOURCES:
        return f"source は {', '.join(BOOK_SOURCES)} のいずれかです。"
    span = max(0, min(int(span), 3))
    ctx.emit({"type": "tool_call", "name": "get_book_pages", "input": {"source": source, "book_id": book_id, "page": page, "span": span}})
    return await _run_fetch(ctx, source, book_id, page=page, span=span, offset=offset)


@beta_async_tool
async def save_memo(title: str, markdown: str) -> str:
    """調査結果をリサーチメモ（Markdown ファイル）として保存する。利用者から保存・メモ化を求められたときに使う。

    Args:
        title: メモの題名（ファイル名にも使う）。
        markdown: メモ本文（Markdown）。引用 ref はそのまま含めてよい。
    """
    ctx = _ctx()
    path = _save_memo(ctx.registry.settings.memos_dir, title, markdown, ctx.hits)
    ctx.emit({"type": "memo_saved", "path": str(path), "title": title})
    return f"保存しました: {path}"


TOOLS = [search_cases, get_case, search_books, get_book_pages, save_memo]
