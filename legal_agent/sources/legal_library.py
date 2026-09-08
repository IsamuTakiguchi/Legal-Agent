"""LEGAL LIBRARY（法律書籍サブスク）。既定では保留（sources/on_hold.py）。

利用規約（令和 8 年 3 月 18 日改定）第 8 条は、
  - 「自動化された手段（情報収集ボット、クローラー、スクレイパーなど）を使用して、本サービスに…アクセスしたりする行為」
  - 「利用者様自身又は第三者の AI 等（…ツール、システム、モデル…）の使用、開発、学習、テスト、検証等をする行為」
  - 「当社が認める方法以外の方法で入力・出力・複製等をする行為」
を禁じている。運営会社から許諾を得た場合のみ `LEGAL_AGENT_LEGAL_LIBRARY_ENABLED=true` でこのブラウザ操作ソースが有効になる。
設定は selectors.yaml の legal_library: 節。
"""
from __future__ import annotations

from ..browser.session import BrowserSession
from ..config import Settings
from .browser_site import BrowserSiteSource
from .on_hold import legal_library_on_hold

# 互換用: 旧名
LegalLibraryLinkSource = legal_library_on_hold


class LegalLibrarySource(BrowserSiteSource):
    def __init__(self, settings: Settings, browser: BrowserSession):
        super().__init__("legal_library", "book", settings, browser)
