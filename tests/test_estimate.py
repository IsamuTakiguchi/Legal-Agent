"""1 問あたりの費用の目安: 実績（assistant ターンの usage.cost_usd）から中央値と範囲を出す。"""
import time

from legal_agent.agent.estimate import estimate, format_estimate, pick, question_samples
from legal_agent.agent.sessions import SessionStore


def _session(store, costs, ts0=None):
    """costs の順に 1 問ずつ（user → assistant）積んだセッションを作る。"""
    s = store.create()
    ts = ts0 or time.time()
    for i, c in enumerate(costs):
        s.turns.append({"role": "user", "text": f"q{i}", "ts": ts + i})
        usage = {"input": 1000 * (i + 1), "output": 500, "cache_read": 0, "cache_write": 0, "turns": 1,
                 "total_input": 1000 * (i + 1), "cost_usd": c}
        if c is None:
            usage["cost_usd"] = None
        s.turns.append({"role": "assistant", "text": f"a{i}", "ts": ts + i + 0.5, "usage": usage})
    store.save(s)
    return s


def test_samples_split_first_and_followup(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    _session(store, [0.10, 0.30, 0.50])
    _session(store, [0.20])
    samples = question_samples(store)
    assert len(samples) == 4
    assert sum(1 for s in samples if not s["followup"]) == 2  # 各セッションの 1 問目
    assert sum(1 for s in samples if s["followup"]) == 2

    est = estimate(store, usd_jpy=150.0)
    assert est["samples"] == 4 and est["usd_jpy"] == 150.0
    assert est["first"]["n"] == 2 and est["first"]["median_usd"] == 0.15  # 0.10 と 0.20
    assert est["followup"]["n"] == 2 and est["followup"]["median_usd"] == 0.40  # 0.30 と 0.50
    assert est["all"]["n"] == 4 and est["all"]["max_usd"] == 0.50
    assert est["all"]["low_usd"] <= est["all"]["median_usd"] <= est["all"]["high_usd"]

    # 表示に使う統計: 続きの質問かどうかで切り替える
    assert pick(est, followup=True)["median_usd"] == 0.40
    assert pick(est, followup=False)["median_usd"] == 0.15
    assert "中央値" in format_estimate(est) and "続きの質問" in format_estimate(est)


def test_no_history_and_unpriced(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    est = estimate(store)
    assert est["samples"] == 0 and est["all"] is None and pick(est) is None
    assert "まだ実績がありません" in format_estimate(est)

    # 単価の分からないモデルの回答（cost_usd が None）は目安に使わない
    _session(store, [None, 0.25])
    est = estimate(store)
    assert est["samples"] == 1 and est["all"]["median_usd"] == 0.25
    assert est["first"] is None and est["followup"]["n"] == 1
    assert pick(est, followup=False)["median_usd"] == 0.25  # first が無ければ全体で代用


def test_limit_keeps_recent(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    old = time.time() - 86400
    _session(store, [9.0], ts0=old)      # 古い高額な 1 問
    _session(store, [0.10, 0.10, 0.10])  # 新しい 3 問
    est = estimate(store, limit=3)
    assert est["samples"] == 3 and est["all"]["max_usd"] == 0.10


def test_prefers_current_model(tmp_path):
    from legal_agent.agent.estimate import MIN_SAME_MODEL

    store = SessionStore(tmp_path / "sessions")
    old = _session(store, [1.0] * 6, ts0=1000)  # 記録にモデル名の無い古い実績
    # 新しいモデルの実績が少ないうちは、全体から出して「前のモデルの分を含む」と示す
    s = _session(store, [0.2] * (MIN_SAME_MODEL - 1), ts0=2000)
    for t in s.turns:
        if t["role"] == "assistant":
            t["usage"]["model"] = "claude-opus-5-5"
    store.save(s)
    est = estimate(store, model="claude-opus-5-5")
    assert est["mixed_models"] is True and est["samples"] == 6 + MIN_SAME_MODEL - 1
    assert "前のモデルの実績を含む" in format_estimate(est)
    # 揃ったら新しいモデルの実績だけを使う
    s.turns.append({"role": "user", "text": "q", "ts": 3000})
    s.turns.append({"role": "assistant", "text": "a", "ts": 3000.5, "usage": {"cost_usd": 0.2, "model": "claude-opus-5-5"}})
    store.save(s)
    est = estimate(store, model="claude-opus-5-5")
    assert est["mixed_models"] is False and est["samples"] == MIN_SAME_MODEL and est["all"]["median_usd"] == 0.2
    # model を渡さなければ従来どおり
    assert estimate(store)["samples"] == 6 + MIN_SAME_MODEL and old is not None
