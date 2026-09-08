"""有効なソースの生成と取得。"""
from __future__ import annotations

from typing import Any

from ..browser.session import BrowserSession
from ..config import Settings
from .base import Source
from .courts import CourtsSource
from .legal_library import LegalLibrarySource
from .local_pdf import LocalPDFSource
from .on_hold import legal_library_on_hold, tkc_on_hold
from .tkc import TKCSource

CASE_SOURCES = ("courts", "tkc")
BOOK_SOURCES = ("local", "legal_library")


class SourceRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.browser = BrowserSession(settings)
        self.local = LocalPDFSource(settings)
        self.courts = CourtsSource(settings)
        # TKC / LEGAL LIBRARY は利用規約の確認結果を踏まえ既定で保留（sources/on_hold.py, docs/TERMS_REVIEW.md 参照）
        self.tkc: Source = TKCSource(settings, self.browser) if settings.tkc_enabled else tkc_on_hold()
        self.legal_library: Source = (
            LegalLibrarySource(settings, self.browser) if settings.legal_library_enabled else legal_library_on_hold()
        )
        self._all: dict[str, Source] = {
            "courts": self.courts,
            "tkc": self.tkc,
            "local": self.local,
            "legal_library": self.legal_library,
        }

    def get(self, name: str) -> Source:
        if name not in self._all:
            raise KeyError(f"不明なソース: {name}（有効: {', '.join(self._all)}）")
        return self._all[name]

    def names(self) -> list[str]:
        return list(self._all)

    def login_sites(self) -> list[str]:
        """ブラウザログインを扱うソース名。"""
        return [n for n, s in self._all.items() if getattr(s, "requires_login", False)]

    def site_config(self, name: str) -> dict[str, Any]:
        src = self._all[name]
        cfg = getattr(src, "cfg", None)
        if cfg is None:
            raise KeyError(f"{name} はブラウザログインを使わないソースです")
        return cfg

    async def statuses(self) -> dict[str, dict[str, Any]]:
        out = {}
        for name, src in self._all.items():
            try:
                st = await src.status()
            except Exception as e:  # noqa: BLE001
                st = {"available": False, "logged_in": None, "detail": str(e)}
            st.update({"label": src.label, "kind": src.kind, "requires_login": src.requires_login})
            out[name] = st
        return out

    async def aclose(self) -> None:
        await self.courts.aclose()
        await self.browser.close()
