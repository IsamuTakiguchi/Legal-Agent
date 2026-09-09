"""selectors.yaml（＋ data/selectors.override.yaml）の設定に従ってログイン必須サイトを Playwright で検索する汎用ソース。

TKC ローライブラリー / LEGAL LIBRARY はどちらもこのクラスで動かす（設定が異なるだけ）。
- ログイン: 認証情報があれば自動ログイン。無ければ LoginRequired（UI で手動ログインを案内）。
- セレクタが合わず結果が取れないときは、Claude による自動発見（browser/autoconf.py）を 1 回試して再検索する。
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import yaml

from ..browser.session import BrowserSession, BrowserUnavailable
from ..config import Settings
from ..models import Document, Hit, Kind, LoginRequired
from .base import slice_text

log = logging.getLogger(__name__)
_SELECTORS_PATH = Path(__file__).with_name("selectors.yaml")
AUTOCONF_RETRY_SEC = 3600


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_site_config(site: str, path: Path | None = None, override_path: Path | None = None) -> dict[str, Any]:
    data = yaml.safe_load((path or _SELECTORS_PATH).read_text(encoding="utf-8"))
    if site not in data:
        raise KeyError(f"selectors.yaml に {site} の設定がありません")
    cfg = data[site]
    if override_path and Path(override_path).exists():
        over = yaml.safe_load(Path(override_path).read_text(encoding="utf-8")) or {}
        if site in over:
            cfg = _deep_merge(cfg, over[site])
            cfg["_override"] = True
    return cfg


class BrowserSiteSource:
    requires_login = True

    def __init__(self, name: str, kind: Kind, settings: Settings, browser: BrowserSession, cfg: dict[str, Any] | None = None):
        self.name = name
        self.kind = kind
        self.settings = settings
        self.browser = browser
        self._explicit_cfg = cfg
        self.cfg = cfg or self._load()
        self.label = self.cfg.get("label", name)
        self._hits: dict[str, Hit] = {}
        self._text_cache: dict[str, str] = {}  # セッション内のみ（ディスクには保存しない）
        self._autoconf_at = 0.0
        self.autoconf_state: dict[str, Any] = {"running": False, "last_result": None, "log": []}
        self._autoconf_lock = asyncio.Lock()

    def _load(self) -> dict[str, Any]:
        return load_site_config(self.name, override_path=self.settings.selectors_override_path)

    def reload(self) -> None:
        if self._explicit_cfg is None:
            self.cfg = self._load()

    # ---- 共通 ----
    async def _ensure_login(self):
        try:
            pg = await self.browser.page(self.name)
        except BrowserUnavailable as e:
            raise LoginRequired(self.name, str(e)) from e
        user, password = self.settings.credentials(self.name)
        ok = await self.browser.ensure_logged_in(self.name, self.cfg, user, password)
        if not ok:
            raise LoginRequired(self.name, self.browser.last_error.get(self.name, ""))
        return pg

    def _make_ref(self, item_id: str) -> str:
        return f"{self.name}:{item_id}"

    @staticmethod
    def _id_from_url(url: str) -> str:
        tail = re.sub(r"^https?://[^/]+/", "", url)
        return re.sub(r"[^A-Za-z0-9._%=-]+", "_", tail)[:120]

    async def _looks_like_login(self, pg) -> bool:
        pat = self.cfg.get("login_url_pattern")
        if pat and re.search(pat, pg.url):
            return True
        form = self.cfg.get("login_form_selector")
        return bool(form) and await pg.locator(form).count() > 0

    # ---- 検索 ----
    async def _do_search(self, pg, query: str) -> None:
        s = self.cfg["search"]
        url = s["url"]
        if "{query}" in url:
            await pg.goto(url.replace("{query}", quote(query)), wait_until="domcontentloaded")
        else:
            await pg.goto(url, wait_until="domcontentloaded")
            await self.browser.dump(self.name, "search-form")
            box = pg.locator(s["input"]).first
            await box.fill(query)
            submit = pg.locator(s["submit"]).first if s.get("submit") else None
            if submit is not None and await submit.count():
                await submit.click()
            else:
                await box.press("Enter")
        try:
            await pg.wait_for_selector(s["results_wait"], timeout=15000)
        except Exception:  # noqa: BLE001
            pass
        await self.browser.dump(self.name, "search-results")

    async def _extract_rows(self, pg, limit: int) -> list[Hit]:
        s = self.cfg["search"]
        rows = pg.locator(s["row"])
        n = min(await rows.count(), int(s.get("max_rows", 20)), limit)
        hits: list[Hit] = []
        for i in range(n):
            row = rows.nth(i)
            title_el = row.locator(s["row_title"]).first if s.get("row_title") else row
            link_el = row.locator(s["row_link"]).first if s.get("row_link") else row
            title = (await title_el.inner_text()).strip() if await title_el.count() else ""
            href = await link_el.get_attribute("href") if await link_el.count() else None
            if not href or re.match(r"^(javascript:|#)", href):
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

    async def search(self, query: str, limit: int = 20, **filters: Any) -> list[Hit]:
        pg = await self._ensure_login()
        hits: list[Hit] = []
        error: Exception | None = None
        try:
            await self._do_search(pg, query)
            if await self._looks_like_login(pg):
                self.browser.login_state[self.name] = False
                raise LoginRequired(self.name)
            hits = await self._extract_rows(pg, limit)
        except LoginRequired:
            raise
        except Exception as e:  # noqa: BLE001
            error = e
            log.warning("%s: 検索に失敗（%s）", self.name, e)
        if hits:
            return hits
        # セレクタが合っていない可能性 → Claude に画面を解析させて再試行
        if await self._maybe_autoconfigure(query):
            pg = await self._ensure_login()
            await self._do_search(pg, query)
            hits = await self._extract_rows(pg, limit)
            if hits:
                return hits
        if error:
            raise RuntimeError(f"{self.label} の検索でエラー: {error}")
        return []

    async def _maybe_autoconfigure(self, query: str) -> bool:
        if not self.settings.auto_configure:
            return False
        if time.monotonic() - self._autoconf_at < AUTOCONF_RETRY_SEC:
            return False
        self._autoconf_at = time.monotonic()
        try:
            await self.autoconfigure(query)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("%s: セレクタ自動発見に失敗: %s", self.name, e)
            return False

    async def autoconfigure(self, query: str = "解雇", client=None, ledger=None) -> dict[str, Any]:
        """Claude で画面構造を解析してセレクタを発見し、override に保存して設定を再読込する。"""
        from ..browser.autoconf import AutoConfigurator, save_override

        async with self._autoconf_lock:
            self.autoconf_state.update({"running": True, "last_result": None})
            ac = AutoConfigurator(self, client=client, model=self.settings.autoconf_model, ledger=ledger)
            try:
                new_cfg = await ac.run(query)
                save_override(self.settings.selectors_override_path, self.name, new_cfg)
                self.reload()
                self.autoconf_state.update({"running": False, "last_result": "ok", "log": ac.log[-12:]})
                return new_cfg
            except Exception as e:
                self.autoconf_state.update({"running": False, "last_result": f"失敗: {e}", "log": ac.log[-12:]})
                raise

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
            if not d.get("text_is_image"):
                for sel in [x.strip() for x in d["content"].split(",") if x.strip()]:
                    try:
                        loc = pg.locator(sel).first
                        if await loc.count():
                            text = (await loc.inner_text()).strip()
                            if len(text) > 200:
                                break
                    except Exception:  # noqa: BLE001
                        continue
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
        user, password = self.settings.credentials(self.name)
        detail = "ログイン済み" if state else ("未ログイン" if state is False else "未確認")
        if state is False and self.browser.last_error.get(self.name):
            detail = self.browser.last_error[self.name]
        return {
            "available": True,
            "logged_in": state,
            "detail": detail,
            "auto_login": bool(user and password),
            "configured": bool(self.cfg.get("_override")),
            "autoconf": self.autoconf_state,
        }
