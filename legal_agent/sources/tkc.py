"""TKC ローライブラリー（判例秘書 / LEX/DB）。設定は selectors.yaml の tkc: 節。"""
from __future__ import annotations

from ..browser.session import BrowserSession
from ..config import Settings
from .browser_site import BrowserSiteSource


class TKCSource(BrowserSiteSource):
    def __init__(self, settings: Settings, browser: BrowserSession):
        super().__init__("tkc", "case", settings, browser)
