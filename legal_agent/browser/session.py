"""Playwright の永続プロファイルで 1 つのブラウザを管理する。

- 認証情報が設定されていれば自動ログイン（フォーム入力）。無ければ表示ブラウザで利用者が手動ログイン。
- Cookie はプロファイルに残るので、通常は 2 回目以降ログイン不要。
- ログイン判定はサイト設定（selectors.yaml）の `login_form_selector` / `logged_in_selector` / `login_url_pattern`。
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
        self.headless = settings.headless
        self._pw = None
        self._ctx: BrowserContext | None = None
        self._pages: dict[str, Page] = {}
        self._lock = asyncio.Lock()
        self._login_locks: dict[str, asyncio.Lock] = {}
        self.login_state: dict[str, bool] = {}
        self.last_error: dict[str, str] = {}

    # ---- 起動・終了 ----
    async def start(self) -> BrowserContext:
        async with self._lock:
            if self._ctx is not None:
                return self._ctx
            if async_playwright is None:
                raise BrowserUnavailable("playwright がインストールされていません（pip install playwright && playwright install chromium）")
            self._pw = await async_playwright().start()
            try:
                kwargs: dict[str, Any] = {}
                if self.settings.chromium_path:
                    kwargs["executable_path"] = self.settings.chromium_path
                self._ctx = await self._pw.chromium.launch_persistent_context(
                    str(self.settings.browser_profile_dir),
                    headless=self.headless,
                    viewport={"width": 1280, "height": 900},
                    locale="ja-JP",
                    **kwargs,
                )
            except Exception as e:  # noqa: BLE001
                raise BrowserUnavailable(f"ブラウザを起動できません（playwright install chromium を実行してください）: {e}") from e
            self._ctx.set_default_timeout(20000)
            return self._ctx

    async def relaunch(self, headless: bool) -> None:
        """表示/非表示を切り替えて再起動（手動ログイン時は表示にする）。"""
        if self._ctx is not None and self.headless == headless:
            return
        await self.close()
        self.headless = headless
        await self.start()

    async def page(self, site: str) -> Page:
        ctx = await self.start()
        pg = self._pages.get(site)
        if pg is None or pg.is_closed():
            pg = await ctx.new_page()
            self._pages[site] = pg
        return pg

    async def close(self) -> None:
        self._pages.clear()
        if self._ctx is not None:
            try:
                await self._ctx.close()
            except Exception:  # noqa: BLE001
                pass
            self._ctx = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None

    # ---- ログイン判定 ----
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
        # ログイン画面ではなく、ログインフォームも無い → ログイン済みとみなす
        return True

    async def check_logged_in(self, site: str, cfg: dict[str, Any]) -> bool:
        pg = await self.page(site)
        await pg.goto(cfg["check_url"], wait_until="domcontentloaded")
        await asyncio.sleep(0.5)
        ok = await self._eval_login_state(pg, cfg)
        self.login_state[site] = ok
        return ok

    # ---- 自動ログイン ----
    async def auto_login(self, site: str, cfg: dict[str, Any], user: str, password: str) -> bool:
        lg = cfg.get("login") or {}
        if not (user and password and lg.get("user") and lg.get("password")):
            return False
        lock = self._login_locks.setdefault(site, asyncio.Lock())
        async with lock:
            if self.login_state.get(site):
                return True
            pg = await self.page(site)
            try:
                await pg.goto(cfg["login_url"], wait_until="domcontentloaded")
                await pg.locator(lg["user"]).first.fill(user)
                await pg.locator(lg["password"]).first.fill(password)
                if lg.get("remember"):
                    box = pg.locator(lg["remember"]).first
                    if await box.count() and not await box.is_checked():
                        await box.check()
                await self.dump(site, "login-filled")
                submit = pg.locator(lg["submit"]).first if lg.get("submit") else None
                if submit is not None and await submit.count():
                    await submit.click()
                else:
                    await pg.locator(lg["password"]).first.press("Enter")
                try:
                    await pg.wait_for_load_state("networkidle", timeout=15000)
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(1.0)
                ok = await self._eval_login_state(pg, cfg)
                if not ok and cfg.get("check_url"):
                    ok = await self.check_logged_in(site, cfg)
                await self.dump(site, "login-after")
                self.login_state[site] = ok
                if not ok:
                    self.last_error[site] = "自動ログインに失敗しました（ID/パスワード、または画面構造の変更を確認してください）"
                return ok
            except Exception as e:  # noqa: BLE001
                self.last_error[site] = f"自動ログイン中にエラー: {e}"
                self.login_state[site] = False
                return False

    async def ensure_logged_in(self, site: str, cfg: dict[str, Any], user: str = "", password: str = "") -> bool:
        """ログイン済みなら True。未ログインなら自動ログインを試みる。"""
        if self.login_state.get(site) is True:
            return True
        if await self.check_logged_in(site, cfg):
            return True
        if user and password:
            return await self.auto_login(site, cfg, user, password)
        return False

    # ---- 手動ログイン ----
    async def wait_for_login(self, site: str, cfg: dict[str, Any], timeout_sec: int = 600) -> bool:
        """表示ブラウザでログイン画面を開き、利用者が手動でログインするのを待つ。"""
        await self.relaunch(headless=False)
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
