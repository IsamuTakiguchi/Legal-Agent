"""Playwright の永続プロファイルで 1 つのブラウザを管理する。

- 利用者が自分で TKC / LEGAL LIBRARY にログインし、Cookie はプロファイルに残る。
- パスワードはアプリに保存しない。
- ログイン判定はサイト設定（selectors.yaml）の `login_form_selector` / `logged_in_selector` で行う。
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any

from ..config import Settings

try:  # Playwright が未インストールでもアプリ全体は動くようにする
    from playwright.async_api import BrowserContext, Page, async_playwright
except Exception:  # noqa: BLE001
    async_playwright = None  # type: ignore
    BrowserContext = Page = Any  # type: ignore


class BrowserUnavailable(Exception):
    pass


class BrowserSession:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._pw = None
        self._ctx: BrowserContext | None = None
        self._pages: dict[str, Page] = {}
        self._lock = asyncio.Lock()
        self.login_state: dict[str, bool] = {}

    async def start(self) -> BrowserContext:
        async with self._lock:
            if self._ctx is not None:
                return self._ctx
            if async_playwright is None:
                raise BrowserUnavailable("playwright がインストールされていません（pip install playwright && playwright install chromium）")
            self._pw = await async_playwright().start()
            try:
                self._ctx = await self._pw.chromium.launch_persistent_context(
                    str(self.settings.browser_profile_dir),
                    headless=self.settings.headless,
                    viewport={"width": 1280, "height": 900},
                    locale="ja-JP",
                )
            except Exception as e:  # noqa: BLE001
                raise BrowserUnavailable(f"ブラウザを起動できません: {e}") from e
            self._ctx.set_default_timeout(20000)
            return self._ctx

    async def page(self, site: str) -> Page:
        ctx = await self.start()
        pg = self._pages.get(site)
        if pg is None or pg.is_closed():
            pg = await ctx.new_page()
            self._pages[site] = pg
        return pg

    async def close(self) -> None:
        if self._ctx is not None:
            await self._ctx.close()
            self._ctx = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None

    # ---- ログイン ----
    async def check_logged_in(self, site: str, cfg: dict[str, Any]) -> bool:
        pg = await self.page(site)
        await pg.goto(cfg["check_url"], wait_until="domcontentloaded")
        ok = await self._eval_login_state(pg, cfg)
        self.login_state[site] = ok
        return ok

    async def _eval_login_state(self, pg: Page, cfg: dict[str, Any]) -> bool:
        pat = cfg.get("login_url_pattern")
        if pat and re.search(pat, pg.url):
            return False
        sel = cfg.get("logged_in_selector")
        if sel and await pg.locator(sel).count() > 0:
            return True
        form = cfg.get("login_form_selector")
        if form and await pg.locator(form).count() > 0:
            return False
        return bool(sel is None and form is None)

    async def wait_for_login(self, site: str, cfg: dict[str, Any], timeout_sec: int = 600) -> bool:
        """ログイン画面を開き、利用者が手動でログインするのを待つ。"""
        pg = await self.page(site)
        await pg.bring_to_front()
        await pg.goto(cfg["login_url"], wait_until="domcontentloaded")
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if pg.is_closed():
                break
            try:
                if await self._eval_login_state(pg, cfg):
                    self.login_state[site] = True
                    return True
            except Exception:  # noqa: BLE001 ページ遷移中など
                pass
            await asyncio.sleep(1.0)
        self.login_state[site] = False
        return False

    # ---- デバッグ ----
    async def dump(self, site: str, step: str) -> None:
        if not self.settings.debug_dump:
            return
        pg = self._pages.get(site)
        if pg is None or pg.is_closed():
            return
        d = Path(self.settings.debug_dir)
        d.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        try:
            (d / f"{stamp}-{site}-{step}.html").write_text(await pg.content(), encoding="utf-8")
            await pg.screenshot(path=str(d / f"{stamp}-{site}-{step}.png"), full_page=True)
        except Exception:  # noqa: BLE001
            pass
