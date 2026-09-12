"""1 問あたりの費用の目安。

質問を送る前に「だいたいいくらか」を知るための見積り。推測ではなく、保存済みセッションに
残っている 1 問ごとの実績（assistant ターンの usage.cost_usd）から中央値と範囲を出す。
最初の質問（新しい調査）と続きの質問では会話履歴の量が違って費用も変わるため、分けて集計する。
"""
from __future__ import annotations

from statistics import median
from typing import Any

# 新しい質問ほど今の設定（モデル・effort）を反映しているので、直近だけを見る
DEFAULT_LIMIT = 30


def question_samples(store: Any) -> list[dict[str, Any]]:
    """保存済みセッションから 1 問ごとの実績を新しい順に取り出す。"""
    out: list[dict[str, Any]] = []
    for item in store.list():
        s = store.get(item["id"])
        if s is None:
            continue
        n = 0
        for t in s.turns:
            if t.get("role") != "assistant":
                continue
            n += 1
            u = t.get("usage") or {}
            cost = u.get("cost_usd")
            if cost is None:
                continue  # 単価の分からないモデルで答えた分は目安に使わない
            out.append({
                "cost_usd": float(cost),
                "followup": n > 1,
                "ts": float(t.get("ts") or s.updated_at or 0),
                "total_input": int(u.get("total_input") or 0),
                "output": int(u.get("output") or 0),
            })
    out.sort(key=lambda d: d["ts"], reverse=True)
    return out


def _pct(vals: list[float], q: float) -> float:
    """並べ替え済みの値から百分位（線形補間なしの簡易版）。"""
    if not vals:
        return 0.0
    i = min(len(vals) - 1, max(0, round(q * (len(vals) - 1))))
    return vals[i]


def _stats(samples: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not samples:
        return None
    vals = sorted(s["cost_usd"] for s in samples)
    return {
        "n": len(vals),
        "median_usd": round(median(vals), 4),
        "mean_usd": round(sum(vals) / len(vals), 4),
        "low_usd": round(_pct(vals, 0.1), 4),
        "high_usd": round(_pct(vals, 0.9), 4),
        "max_usd": round(vals[-1], 4),
        "median_input": int(median(sorted(s["total_input"] for s in samples))),
        "median_output": int(median(sorted(s["output"] for s in samples))),
    }


def estimate(store: Any, usd_jpy: float = 150.0, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """直近 limit 問の実績から、1 問あたりの費用の目安を返す。実績が無ければ samples=0。"""
    samples = question_samples(store)[:limit]
    return {
        "samples": len(samples),
        "usd_jpy": usd_jpy,
        "all": _stats(samples),
        "first": _stats([s for s in samples if not s["followup"]]),
        "followup": _stats([s for s in samples if s["followup"]]),
    }


def pick(est: dict[str, Any] | None, followup: bool = False) -> dict[str, Any] | None:
    """表示に使う統計を選ぶ。続きの質問なら followup、無ければ全体にフォールバック。"""
    if not est:
        return None
    key = "followup" if followup else "first"
    return est.get(key) or est.get("all")


def format_estimate(est: dict[str, Any] | None) -> str:
    """CLI / doctor 用の 1〜3 行。"""
    if not est or not est.get("samples"):
        return "1 問あたりの目安: まだ実績がありません（最初の質問のあとに表示されます）"
    rate = est.get("usd_jpy") or 150.0
    lines = []
    for key, label in (("first", "新しい調査の 1 問目"), ("followup", "続きの質問"), ("all", "全体")):
        st = est.get(key)
        if not st:
            continue
        yen = round(st["median_usd"] * rate)
        lines.append(f"  {label}: 中央値 約 ${st['median_usd']:.2f}（約 {yen:,} 円）"
                     f"／よくある範囲 ${st['low_usd']:.2f}〜${st['high_usd']:.2f}（{st['n']} 問）")
    return "1 問あたりの目安（直近の実績）:\n" + "\n".join(lines)
