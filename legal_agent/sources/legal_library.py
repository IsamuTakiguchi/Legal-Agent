"""LEGAL LIBRARY（法律書籍サブスク）。設定は selectors.yaml の legal_library: 節。"""
from __future__ import annotations

from ..browser.session import BrowserSession
from ..config import Settings
from .browser_site import BrowserSiteSource


class LegalLibrarySource(BrowserSiteSource):
    def __init__(self, settings: Settings, browser: BrowserSession):
        super().__init__("legal_library", "book", settings, browser)
