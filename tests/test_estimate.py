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
