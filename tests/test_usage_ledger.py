"""API 利用の台帳: 記録・月集計・過去セッションの取り込み。"""
from types import SimpleNamespace

from legal_agent.agent.sessions import SessionStore
from legal_agent.agent.usage_ledger import UsageLedger, current_month, format_table, month_of, month_view


def U(**kw):
    return SimpleNamespace(**{"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, **kw})


def test_record_and_month_summary(tmp_path):
    led = UsageLedger(tmp_path / "usage.sqlite3")
    r = led.record(U(input_tokens=1000, output_tokens=100, cache_read_input_tokens=10000, cache_creation_input_tokens=500), "claude-opus-5", "chat", "s1")
    # 1000*5 + 100*25 + 10000*0.5 + 500*6.25 = 15625 / 1e6
    assert abs(r["cost_usd"] - 0.015625) < 1e-9 and r["month"] == current_month()
    assert led.record(None, "claude-opus-5") is None
    led.record(U(input_tokens=100, output_tokens=10), "claude-sonnet-5", "chat", "s1")
    led.record(U(input_tokens=100, output_tokens=10), "mystery-model", "autoconf", "tkc")
    s = led.month_summary()
    assert s["calls"] == 3 and s["input"] == 1200 and s["output"] == 120 and s["cache_read"] == 10000
    assert s["unpriced_calls"] == 1 and set(s["by_model"]) == {"claude-opus-5", "claude-sonnet-5", "mystery-model"}
    assert abs(s["cost_usd"] - (0.015625 + (100 * 2 + 10 * 10) / 1e6)) < 1e-9
    assert s["total_input"] == 1200 + 10000 + 500
    assert led.total_calls() == 3

    # 過去の月も出る（新しい順、今月が先頭）
    led.record(U(input_tokens=10, output_tokens=1), "claude-opus-5", "chat", "s0", ts=1_700_000_000)  # 2023-11
    ms = led.months()
    assert [m["month"] for m in ms][:1] == [current_month()] and ms[-1]["month"] == month_of(1_700_000_000)
    assert ms[-1]["calls"] == 1

    mv = month_view(led, usd_jpy=150.0, budget_usd=0.01)
    assert mv["over_budget"] is True and mv["cost_jpy"] == round(mv["cost_usd"] * 150)
    assert month_view(led, 150.0, 0)["over_budget"] is False
    table = format_table(ms, 150.0)
    assert current_month() in table and "1 USD = 150 円" in table


def test_empty_month_is_present(tmp_path):
    led = UsageLedger(tmp_path / "u.sqlite3")
    ms = led.months()
    assert len(ms) == 1 and ms[0]["month"] == current_month() and ms[0]["cost_usd"] == 0.0 and ms[0]["calls"] == 0


def test_backfill_from_sessions_once(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    s = store.create()
    s.turns = [
        {"role": "user", "text": "q", "ts": 1_700_000_000.0},
        {"role": "assistant", "text": "a", "ts": 1_700_000_001.0, "usage": {"input": 100, "output": 20, "cache_read": 0, "cache_write": 0, "turns": 1}},
        {"role": "assistant", "text": "b", "ts": 1_700_000_002.0, "usage": {"input": 50, "output": 5, "cache_read": 0, "cache_write": 0, "turns": 1}},
    ]
    store.save(s)
    led = UsageLedger(tmp_path / "u.sqlite3")
    assert led.backfill_from_sessions(store, "claude-opus-5") == 2
    assert led.backfill_from_sessions(store, "claude-opus-5") == 0  # 2 回目は何もしない
    m = led.month_summary(month_of(1_700_000_001.0))
    assert m["calls"] == 2 and m["input"] == 150 and m["output"] == 25
    assert abs(m["cost_usd"] - (150 * 5 + 25 * 25) / 1e6) < 1e-9
    # 再オープンしてもフラグが残る
    led2 = UsageLedger(tmp_path / "u.sqlite3")
    assert led2.backfill_from_sessions(store, "claude-opus-5") == 0 and led2.total_calls() == 2
