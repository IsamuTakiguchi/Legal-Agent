"""トークン節約: 履歴圧縮・使用量集計・focus 抜粋・本文の初回制限。"""
from types import SimpleNamespace

import pytest

from legal_agent.agent.costs import UsageTotals, compact_history, strip_private_keys
from legal_agent.sources.base import focus_excerpts


def test_usage_totals_and_cost():
    t = UsageTotals()
    t.add(SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=9000, cache_creation_input_tokens=500))
    t.add(SimpleNamespace(input_tokens=500, output_tokens=100, cache_read_input_tokens=None, cache_creation_input_tokens=0))
    d = t.to_dict("claude-opus-5")
    assert d["input"] == 1500 and d["output"] == 300 and d["cache_read"] == 9000 and d["cache_write"] == 500 and d["turns"] == 2
    assert d["total_input"] == 11000
    # 1500*5 + 300*25 + 9000*0.5 + 500*6.25 = 7500+7500+4500+3125 = 22625 / 1e6
    assert abs(d["cost_usd"] - 0.022625) < 1e-9
    assert UsageTotals().to_dict("unknown-model")["cost_usd"] is None
    c = UsageTotals()
    c.add_dict(d)
    c.add_dict(None)
    assert c.to_dict()["total_input"] == 11000


def test_compact_history_only_past_turns():
    long_text = "判決本文" * 500  # 2000 字
    messages = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "…", "signature": "s"}, {"type": "tool_use", "id": "t1", "name": "get_case", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": long_text}]},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "…"}, {"type": "text", "text": "結論[1]"}]},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t2", "name": "get_case", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2", "content": long_text}]},
    ]
    changed = compact_history(messages, upto=4)
    assert changed == 3  # tool_result 1 件 + thinking 2 件
    tr = messages[2]["content"][0]
    assert tr["_compacted"] is True and tr["content"].startswith("判決本文" * 10) and "省略: 全 2000 字" in tr["content"]
    assert len(tr["content"]) < 400
    assert messages[1]["content"] == [{"type": "tool_use", "id": "t1", "name": "get_case", "input": {}}]
    assert messages[3]["content"] == [{"type": "text", "text": "結論[1]"}]
    # 最新ターンは無傷
    assert messages[6]["content"][0]["content"] == long_text
    # 2 回目は何もしない
    assert compact_history(messages, upto=4) == 0
    sent = strip_private_keys(messages)
    assert "_compacted" not in sent[2]["content"][0] and "_compacted" in messages[2]["content"][0]


def test_compact_history_thinking_only_block():
    messages = [{"role": "assistant", "content": [{"type": "thinking", "thinking": "x"}]}]
    compact_history(messages, upto=1)
    assert messages[0]["content"] == [{"type": "text", "text": "（省略）"}]


def test_focus_excerpts():
    text = "あ" * 1000 + "解雇権濫用" + "い" * 1000 + "整理解雇の四要件" + "う" * 1000
    out = focus_excerpts(text, "解雇権濫用 四要件", window=200, max_windows=5)
    assert "解雇権濫用" in out and "四要件" in out
    assert len(out) < 700  # 2 窓 × 200 字 + 見出し
    assert "（1000 字目〜）" in out or "（900 字目〜）" in out
    assert focus_excerpts(text, "存在しない") == ""
    assert focus_excerpts("", "x") == "" and focus_excerpts(text, "   ") == ""
    # 近接する出現は 1 窓にまとまる
    dense = "x" * 100 + "甲" + "y" * 50 + "乙" + "z" * 100
    assert focus_excerpts(dense, "甲 乙", window=200).count("…（") == 1


@pytest.mark.anyio
async def test_courts_fetch_initial_focus_and_offset(settings, tmp_path, monkeypatch):
    import json

    from legal_agent.sources.courts import CourtsSource

    settings.initial_text_chars = 100
    settings.max_text_chars = 150
    src = CourtsSource(settings)
    body = "主文" + "本件請求を棄却する。" * 20 + "整理解雇の四要件" + "理由" * 200
    src._cache_path("1").write_text(json.dumps({"case_id": "1", "detail_url": "u", "pdf_url": "p", "meta": {"事件番号": "令和1(ワ)1", "裁判要旨": "要旨です"}, "text": body}), encoding="utf-8")
    d0 = await src.fetch("1")
    assert len(d0.text) == 100 and d0.meta["裁判要旨"] == "要旨です" and d0.total_chars == len(body)
    assert "続きは offset=100" in d0.to_tool_text()
    d1 = await src.fetch("1", offset=100)
    assert len(d1.text) == 150 and d1.offset == 100
    df = await src.fetch("1", focus="四要件")
    assert "整理解雇の四要件" in df.text and len(df.text) < 900 and "focus=" in df.meta["抜粋"]
    dn = await src.fetch("1", focus="存在しない語")
    assert "見つかりませんでした" in dn.text
    await src.aclose()


@pytest.mark.anyio
async def test_local_page_cap(settings, tmp_path):
    from legal_agent.index.db import IndexDB
    from legal_agent.sources.local_pdf import LocalPDFSource

    settings.max_page_chars = 50
    db = IndexDB(tmp_path / "i.sqlite3")
    db.add_document("b", "/b.pdf", "本", "", "", 1, 1, [(1, "あ" * 200), (2, "い" * 10)])
    src = LocalPDFSource(settings, db)
    d = await src.fetch("b", page=1, span=0)
    assert "あ" * 50 in d.text and "あ" * 51 not in d.text and "50 字で省略" in d.text
    d = await src.fetch("b", page=2, span=0)
    assert "省略" not in d.text
