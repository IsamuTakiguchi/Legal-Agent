from datetime import date

from legal_agent.sources.courts import build_params, clean_judgment_text, parse_detail, parse_iso, parse_list, to_wareki

from conftest import FIXTURES


def test_parse_list_fixture():
    hits, total = parse_list((FIXTURES / "courts_list.html").read_text(encoding="utf-8"))
    assert total == 1766
    assert len(hits) == 30
    h = hits[0]
    assert h.ref == "courts:96707"
    assert h.meta["case_number"] == "令和5(ワ)234"
    assert "退職手当等請求事件" in h.title
    assert h.meta["court"] == "大津地方裁判所"
    assert h.meta["date"] == "令和8年6月5日"
    assert h.url == "https://www.courts.go.jp/hanrei/96707/detail4/index.html"
    assert h.meta["pdf_url"] == "https://www.courts.go.jp/assets/hanrei/hanrei-pdf-96707.pdf"
    h2 = hits[1]
    assert h2.meta["result"] == "破棄自判"
    assert "大阪地方裁判所" in h2.meta["original"]


def test_parse_detail_fixture():
    meta = parse_detail((FIXTURES / "courts_detail.html").read_text(encoding="utf-8"))
    assert meta["事件番号"] == "令和5(行ヒ)366"
    assert meta["裁判年月日"] == "令和8年6月16日"
    assert meta["法廷名"] == "最高裁判所第三小法廷"
    assert "所得税法" in meta["判示事項"]
    assert meta["pdf_url"] == "https://www.courts.go.jp/assets/hanrei/hanrei-pdf-96174.pdf"


def test_wareki():
    assert to_wareki(date(2026, 9, 8)) == ("令和", 8)
    assert to_wareki(date(2019, 4, 30)) == ("平成", 31)
    assert to_wareki(date(1988, 1, 1)) == ("昭和", 63)
    assert parse_iso("2025") == date(2025, 1, 1)
    assert parse_iso("2025/03/04") == date(2025, 3, 4)
    assert parse_iso("bad") is None


def test_build_params():
    p = build_params("解雇", date_from="2025-01-01", date_to="2026-12-31", court="大阪高等裁判所", offset=30)
    assert p["query1"] == "解雇"
    assert p["filter[judgeDateMode]"] == "2"
    assert (p["filter[judgeGengoFrom]"], p["filter[judgeYearFrom]"]) == ("令和", "7")
    assert (p["filter[judgeMonthTo]"], p["filter[judgeDayTo]"]) == ("12", "31")
    assert p["filter[courtName]"] == "大阪高等裁判所"
    assert p["offset"] == "30"
    # 期間指定なしのときは judgeDateMode を送らない（送ると結果ブロックが描画されない）
    assert "filter[judgeDateMode]" not in build_params("解雇")
    assert build_params("x")["filter[jikenNumber]"] == ""


def test_clean_judgment_text():
    assert clean_judgment_text("主 文\n5\n本件訴えを却下する。\n 10 \n第1 請求") == "主 文\n本件訴えを却下する。\n第1 請求"
