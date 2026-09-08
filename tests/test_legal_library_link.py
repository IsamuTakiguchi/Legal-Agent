"""LEGAL LIBRARY は既定でサイトにアクセスせず、手動検索の案内だけを返すこと。"""
import pytest

from legal_agent.sources.legal_library import LegalLibraryLinkSource, LegalLibrarySource
from legal_agent.sources.registry import SourceRegistry

pytestmark = pytest.mark.anyio


async def test_default_is_link_only(settings):
    reg = SourceRegistry(settings)
    try:
        assert isinstance(reg.legal_library, LegalLibraryLinkSource)
        assert reg.login_sites() == ["tkc"]
        hits = await reg.get("legal_library").search("解雇 整理解雇")
        assert len(hits) == 1
        assert hits[0].url == "https://legal-library.jp/search?keyword=%E8%A7%A3%E9%9B%87%20%E6%95%B4%E7%90%86%E8%A7%A3%E9%9B%87"
        assert hits[0].meta["manual"] is True and "第 8 条" in hits[0].snippet
        with pytest.raises(KeyError):
            await reg.get("legal_library").fetch("x")
        st = await reg.get("legal_library").status()
        assert st["available"] is False and st["manual_only"] is True
        with pytest.raises(KeyError):
            reg.site_config("legal_library")
    finally:
        await reg.aclose()


async def test_enabled_uses_browser_source(settings):
    settings.legal_library_enabled = True
    reg = SourceRegistry(settings)
    try:
        assert isinstance(reg.legal_library, LegalLibrarySource)
        assert reg.login_sites() == ["tkc", "legal_library"]
        assert reg.site_config("legal_library")["login"]["user"] == "#email"
    finally:
        await reg.aclose()
