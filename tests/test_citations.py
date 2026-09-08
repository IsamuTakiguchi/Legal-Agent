from legal_agent.agent.citations import citations_footer, resolve_citations
from legal_agent.memo.export import save_memo
from legal_agent.models import Hit


def _hits():
    return {
        "courts:1": Hit(ref="courts:1", source="courts", kind="case", title="令和5(ワ)1 事件", subtitle="東京地裁", url="https://x/1"),
        "local:a:p3": Hit(ref="local:a:p3", source="local", kind="book", title="労働法", subtitle="p.3", url="/pdf/a#page=3"),
    }


def test_resolve_citations_numbers_in_order_and_dedup():
    text = "解雇は無効[[courts:1]]。学説も同旨[[ local:a:p3 ]]。再掲[[courts:1]]。捏造[[tkc:zzz]]。"
    out, cites = resolve_citations(text, _hits())
    assert out == "解雇は無効[1]。学説も同旨[2]。再掲[1]。捏造[出典不明: tkc:zzz]。"
    assert [(c.number, c.hit.ref) for c in cites] == [(1, "courts:1"), (2, "local:a:p3")]
    footer = citations_footer(cites)
    assert "[1] 令和5(ワ)1 事件（東京地裁） https://x/1" in footer
    assert citations_footer([]) == ""


def test_save_memo(tmp_path):
    p = save_memo(tmp_path / "memos", "整理解雇: 調査/メモ", "結論[[courts:1]]", _hits())
    assert p.exists() and p.suffix == ".md"
    body = p.read_text(encoding="utf-8")
    assert "# 整理解雇: 調査/メモ" in body and "結論[1]" in body and "出典:" in body
