"""TKC / LEGAL LIBRARY は既定で保留: サイトにアクセスせず、手動検索の案内だけを返すこと。"""
import pytest

from legal_agent.sources.legal_library import LegalLibrarySource
from legal_agent.sources.on_hold import OnHoldSource
from legal_agent.sources.registry import SourceRegistry
from legal_agent.sources.tkc import TKCSource

pytestmark = pytest.mark.anyio


async def test_default_both_on_hold(settings):
    reg = SourceRegistry(settings)
    try:
        assert isinstance(reg.tkc, OnHoldSource) and isinstance(reg.legal_library, OnHoldSource)
        assert reg.login_sites() == []
        hits = await reg.get("legal_library").search("解雇 整理解雇")
        assert len(hits) == 1
        assert hits[0].url == "https://legal-library.jp/search?keyword=%E8%A7%A3%E9%9B%87%20%E6%95%B4%E7%90%86%E8%A7%A3%E9%9B%87"
        assert hits[0].meta["manual"] is True and "第 8 条" in hits[0].snippet
        tk = await reg.get("tkc").search("解雇")
        assert tk[0].url == "https://www.lawlibrary.jp/Law/LoginForm.aspx" and tk[0].kind == "case" and "保留" in tk[0].snippet
        with pytest.raises(KeyError):
            await reg.get("legal_library").fetch("x")
        for name in ("tkc", "legal_library"):
            st = await reg.get(name).status()
            assert st["available"] is False and st["manual_only"] is True
            with pytest.raises(KeyError):
                reg.site_config(name)
    finally:
        await reg.aclose()


async def test_enabled_uses_browser_sources(settings):
    settings.tkc_enabled = True
    settings.legal_library_enabled = True
    reg = SourceRegistry(settings)
    try:
        assert isinstance(reg.tkc, TKCSource) and isinstance(reg.legal_library, LegalLibrarySource)
        assert reg.login_sites() == ["tkc", "legal_library"]
        assert reg.site_config("legal_library")["login"]["user"] == "#email"
        assert reg.site_config("tkc")["login"]["user"] == "#LoginAccount"
    finally:
        await reg.aclose()
