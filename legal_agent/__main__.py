"""CLI: python -m legal_agent serve | index | login <site> | search-cases <q> | search-books <q>"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import get_settings


def cmd_serve(args: argparse.Namespace) -> None:
    import threading
    import webbrowser

    import uvicorn

    from .app import create_app

    s = get_settings()
    host = args.host or s.host
    port = args.port or s.port
    url = f"http://{host}:{port}/"
    print(f"Legal-Agent: {url}  (model={s.model}, effort={s.effort})", file=sys.stderr)
    if s.auto_open_browser and not getattr(args, "no_open", False):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(s), host=host, port=port, log_level="info")


def cmd_setup(args: argparse.Namespace) -> None:
    from .setup_wizard import run_setup

    run_setup(non_interactive=args.non_interactive)


def cmd_index(args: argparse.Namespace) -> None:
    from pathlib import Path

    from .index.db import IndexDB
    from .index.indexer import index_dirs

    s = get_settings()
    dirs = [Path(p) for p in args.paths] or s.pdf_dirs
    if not dirs:
        sys.exit("PDF フォルダを引数か LEGAL_AGENT_PDF_DIRS で指定してください")
    db = IndexDB(s.db_path)
    stats = index_dirs(db, dirs, rebuild=args.rebuild)
    print(stats)


async def _login(site: str) -> None:
    from .sources.registry import SourceRegistry

    s = get_settings()
    reg = SourceRegistry(s)
    try:
        cfg = reg.site_config(site)
        print(f"ブラウザを開きます。{cfg.get('label', site)} にログインしてください…", file=sys.stderr)
        ok = await reg.browser.wait_for_login(site, cfg)
        print("ログイン成功。セッションはブラウザプロファイルに保存されました。" if ok else "ログインを確認できませんでした。selectors.yaml の logged_in_selector を確認してください。")
    finally:
        await reg.aclose()


async def _autoconf(site: str, query: str) -> None:
    from .sources.registry import SourceRegistry

    s = get_settings()
    reg = SourceRegistry(s)
    try:
        src = reg.get(site)
        print(f"{src.label}: Claude で画面構造を解析しています…", file=sys.stderr)
        cfg = await src.autoconfigure(query)
        print("保存しました:", s.selectors_override_path)
        for line in cfg.get("autoconf_log", []):
            print(" -", line)
        for h in await src.search(query, limit=5):
            print("-", h.to_tool_text())
    finally:
        await reg.aclose()


async def _search(kind: str, query: str, source: str | None) -> None:
    from .sources.registry import BOOK_SOURCES, CASE_SOURCES, SourceRegistry

    s = get_settings()
    reg = SourceRegistry(s)
    names = [source] if source else list(CASE_SOURCES if kind == "case" else BOOK_SOURCES)
    try:
        for n in names:
            src = reg.get(n)
            print(f"=== {src.label} ===")
            try:
                for h in await src.search(query, limit=10):
                    print("-", h.to_tool_text())
            except Exception as e:  # noqa: BLE001
                print(f"エラー: {type(e).__name__}: {e}")
    finally:
        await reg.aclose()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="legal-agent", description="引数なしで起動すると、初回は setup、以後は serve を実行します。")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("serve", help="Web UI を起動（ブラウザが自動で開く）")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("setup", help="初回セットアップ（.env 生成・Chromium 導入・索引）")
    p.add_argument("--non-interactive", action="store_true")
    p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("autoconf", help="Claude でサイトのセレクタを自動発見して保存")
    p.add_argument("site", choices=["tkc", "legal_library"])
    p.add_argument("--query", default="解雇")
    p.set_defaults(fn=lambda a: asyncio.run(_autoconf(a.site, a.query)))
    p = sub.add_parser("index", help="書籍 PDF を索引化")
    p.add_argument("paths", nargs="*")
    p.add_argument("--rebuild", action="store_true")
    p.set_defaults(fn=cmd_index)
    p = sub.add_parser("login", help="TKC / LEGAL LIBRARY に手動ログイン")
    p.add_argument("site", choices=["tkc", "legal_library"])
    p.set_defaults(fn=lambda a: asyncio.run(_login(a.site)))
    p = sub.add_parser("search-cases", help="判例検索を CLI で試す")
    p.add_argument("query")
    p.add_argument("--source", choices=["courts", "tkc"])
    p.set_defaults(fn=lambda a: asyncio.run(_search("case", a.query, a.source)))
    p = sub.add_parser("search-books", help="文献検索を CLI で試す")
    p.add_argument("query")
    p.add_argument("--source", choices=["local", "legal_library"])
    p.set_defaults(fn=lambda a: asyncio.run(_search("book", a.query, a.source)))
    args = ap.parse_args(argv)
    if args.cmd is None:
        from pathlib import Path

        if not Path(".env").exists():
            cmd_setup(argparse.Namespace(non_interactive=False))
        cmd_serve(argparse.Namespace(host=None, port=None, no_open=False))
        return
    args.fn(args)


if __name__ == "__main__":
    main()
