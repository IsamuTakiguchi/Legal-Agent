"""selectors.yaml の設定に従ってログイン必須サイトを Playwright で検索する汎用ソース。

TKC ローライブラリー / LEGAL LIBRARY はどちらもこのクラスで動かす（設定が異なるだけ）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import yaml

from ..browser.session import BrowserSession, BrowserUnavailable
from ..config import Settings
from ..models import Document, Hit, Kind, LoginRequired
from .base import slice_text

_SELECTORS_PATH = Path(__file__).with_name("selectors.yaml")


def load_site_config(site: str, path: Path | None = None) -> dict[str, Any]:
    data = yaml.safe_load((path or _SELECTORS_PATH).read_text(encoding="utf-8"))
    if site not in data:
        raise KeyError(f"selectors.yaml に {site} の設定がありません")
    return data[site]


class BrowserSiteSource:
    requires_login = True

    def __init__(self, name: str, kind: Kind, settings: Settings, browser: BrowserSession, cfg: dict[str, Any] | None = None):
        self.name = name
        self.kind = kind
        self.settings = settings
        self.browser = browser
        self.cfg = cfg or load_site_config(name)
        self.label = self.cfg.get("label", name)
        self._hits: dict[str, Hit] = {}
        self._text_cache: dict[str, str] = {}  # セッション内のみ（ディスクには保存しない）

    # ---- 共通 ----
    async def _ensure_login(self):
        try:
            pg = await self.browser.page(self.name)
        except BrowserUnavailable as e:
            raise LoginRequired(self.name, str(e)) from e
        if self.browser.login_state.get(self.name) is not True:
            ok = await self.browser.check_logged_in(self.name, self.cfg)
            if not ok:
                raise LoginRequired(self.name)
        return pg

    def _make_ref(self, item_id: str) -> str:
        return f"{self.name}:{item_id}"

    @staticmethod
    def _id_from_url(url: str) -> str:
        # URL の末尾から ID らしき部分を作る（安定性重視でハッシュは使わない）
        tail = re.sub(r"^https?://[^/]+/", "", url)
        return re.sub(r"[^A-Za-z0-9._%=-]+", "_", tail)[:120]

    # ---- 検索 ----
    async def search(self, query: str, limit: int = 20, **filters: Any) -> list[Hit]:
        pg = await self._ensure_login()
        s = self.cfg["search"]
        url = s["url"]
        if "{query}" in url:
            await pg.goto(url.replace("{query}", quote(query)), wait_until="domcontentloaded")
        else:
            await pg.goto(url, wait_until="domcontentloaded")
            await self.browser.dump(self.name, "search-form")
            box = pg.locator(s["input"]).first
            await box.fill(query)
            submit = pg.locator(s["submit"]).first
            if await submit.count():
                await submit.click()
            else:
                await box.press("Enter")
        try:
            await pg.wait_for_selector(s["results_wait"], timeout=15000)
        except Exception:  # noqa: BLE001
            pass
        await self.browser.dump(self.name, "search-results")
        if await self._looks_like_login(pg):
            self.browser.login_state[self.name] = False
            raise LoginRequired(self.name)

        rows = pg.locator(s["row"])
        n = min(await rows.count(), int(s.get("max_rows", 20)), limit)
        hits: list[Hit] = []
        for i in range(n):
            row = rows.nth(i)
            title_el = row.locator(s["row_title"]).first if s.get("row_title") else row
            link_el = row.locator(s["row_link"]).first if s.get("row_link") else row
            title = (await title_el.inner_text()).strip() if await title_el.count() else ""
            href = await link_el.get_attribute("href") if await link_el.count() else None
            if not href:
                continue
            href = urljoin(pg.url, href)
            meta_text = ""
            if s.get("row_meta"):
                cells = row.locator(s["row_meta"])
                texts = [(await cells.nth(j).inner_text()).strip() for j in range(min(await cells.count(), 8))]
                meta_text = " / ".join(t for t in texts if t and t != title)
            item_id = self._id_from_url(href)
            title = re.sub(r"\s+", " ", title)[:200] or href
            hit = Hit(
                ref=self._make_ref(item_id), source=self.name, kind=self.kind, title=title,
                subtitle=re.sub(r"\s+", " ", meta_text)[:300], snippet="", url=href,
                meta={"item_id": item_id},
            )
            self._hits[item_id] = hit
            hits.append(hit)
        return hits

    async def _looks_like_login(self, pg) -> bool:
        pat = self.cfg.get("login_url_pattern")
        if pat and re.search(pat, pg.url):
            return True
        form = self.cfg.get("login_form_selector")
        return bool(form) and await pg.locator(form).count() > 0

    # ---- 本文 ----
    async def fetch(self, item_id: str, **options: Any) -> Document:
        item_id = item_id.split(":", 1)[1] if item_id.startswith(self.name + ":") else item_id
        offset = int(options.get("offset", 0))
        hit = self._hits.get(item_id)
        if hit is None:
            raise KeyError(f"{self.label} の項目 {item_id} はこのセッションの検索結果にありません。先に検索してください。")
        if item_id not in self._text_cache:
            pg = await self._ensure_login()
            await pg.goto(hit.url, wait_until="domcontentloaded")
            d = self.cfg["detail"]
            try:
                await pg.wait_for_selector(d["wait"], timeout=15000)
            except Exception:  # noqa: BLE001
                pass
            await self.browser.dump(self.name, "detail")
            if await self._looks_like_login(pg):
                self.browser.login_state[self.name] = False
                raise LoginRequired(self.name)
            text = ""
            for sel in [x.strip() for x in d["content"].split(",")]:
                loc = pg.locator(sel).first
                if await loc.count():
                    text = (await loc.inner_text()).strip()
                    if len(text) > 200:
                        break
            if len(text) < 50:
                text = (
                    "（このページから本文テキストを取得できませんでした。画像表示のビューアの可能性があります。"
                    f"利用者にはブラウザで開いて確認するよう案内してください: {hit.url}）"
                )
            self._text_cache[item_id] = text
        text, total = slice_text(self._text_cache[item_id], offset, self.settings.max_text_chars)
        return Document(
            ref=hit.ref, source=self.name, kind=self.kind, title=hit.title, text=text, url=hit.url,
            meta={"情報": hit.subtitle}, offset=offset, total_chars=total,
        )

    async def status(self) -> dict[str, Any]:
        state = self.browser.login_state.get(self.name)
        return {
            "available": True,
            "logged_in": state,
            "detail": "ログイン済み" if state else ("未ログイン" if state is False else "未確認"),
        }
