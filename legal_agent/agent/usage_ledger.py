"""API 利用の台帳: すべての Claude API 呼び出しを SQLite に記録し、月ごとの利用料（概算）を出す。

Anthropic の公式コスト API（Admin API）は個人アカウントでは使えないため、アプリ側で
応答の usage（トークン数）を記録し、PRICES の単価で概算する。正式な請求額は Console の
Cost ページ（https://platform.claude.com/cost）で確認する。
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .costs import price_for

CONSOLE_COST_URL = "https://platform.claude.com/cost"
NOTE = "アプリが記録したトークン数から単価表で計算した概算です。正式な請求額は Anthropic Console の Cost ページで確認してください。"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    month TEXT NOT NULL,
    model TEXT NOT NULL,
    kind TEXT NOT NULL,
    session_id TEXT,
    input INTEGER NOT NULL DEFAULT 0,
    output INTEGER NOT NULL DEFAULT 0,
    cache_read INTEGER NOT NULL DEFAULT 0,
    cache_write INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL
);
CREATE INDEX IF NOT EXISTS api_calls_month ON api_calls(month);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def month_of(ts: float) -> str:
    """ローカル時刻での 'YYYY-MM'。"""
    return datetime.fromtimestamp(ts).strftime("%Y-%m")


def current_month() -> str:
    return month_of(time.time())


def cost_of(model: str, input: int, output: int, cache_read: int, cache_write: int) -> float | None:
    p = price_for(model or "")
    if p is None:
        return None
    i, o, r, w = p
    return (input * i + output * o + cache_read * r + cache_write * w) / 1_000_000


class UsageLedger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.executescript(_SCHEMA)

    # ---- 記録 ----
    def record(self, usage: Any, model: str, kind: str = "chat", session_id: str | None = None, ts: float | None = None) -> dict[str, Any] | None:
        """SDK の usage（input_tokens など）を 1 件記録する。usage が無ければ何もしない。"""
        if usage is None:
            return None
        row = {
            "ts": ts or time.time(),
            "model": model or "",
            "kind": kind,
            "session_id": session_id,
            "input": int(getattr(usage, "input_tokens", 0) or 0),
            "output": int(getattr(usage, "output_tokens", 0) or 0),
            "cache_read": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            "cache_write": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        }
        return self._insert(row)

    def record_dict(self, d: dict[str, Any], model: str, kind: str, session_id: str | None, ts: float) -> dict[str, Any] | None:
        """UsageTotals.to_dict() 形式（input/output/cache_read/cache_write）を記録する。"""
        if not d:
            return None
        row = {"ts": ts, "model": model or "", "kind": kind, "session_id": session_id,
               "input": int(d.get("input", 0) or 0), "output": int(d.get("output", 0) or 0),
               "cache_read": int(d.get("cache_read", 0) or 0), "cache_write": int(d.get("cache_write", 0) or 0)}
        return self._insert(row)

    def _insert(self, row: dict[str, Any]) -> dict[str, Any]:
        row["month"] = month_of(row["ts"])
        row["cost_usd"] = cost_of(row["model"], row["input"], row["output"], row["cache_read"], row["cache_write"])
        with self.conn:
            self.conn.execute(
                "INSERT INTO api_calls (ts, month, model, kind, session_id, input, output, cache_read, cache_write, cost_usd)"
                " VALUES (:ts, :month, :model, :kind, :session_id, :input, :output, :cache_read, :cache_write, :cost_usd)",
                row,
            )
        return row

    # ---- 集計 ----
    @staticmethod
    def _empty(month: str) -> dict[str, Any]:
        return {"month": month, "calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0, "unpriced_calls": 0, "by_model": {}}

    def month_summary(self, month: str | None = None) -> dict[str, Any]:
        month = month or current_month()
        s = self._empty(month)
        rows = self.conn.execute(
            "SELECT model, COUNT(*), SUM(input), SUM(output), SUM(cache_read), SUM(cache_write), SUM(cost_usd),"
            " SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END) FROM api_calls WHERE month = ? GROUP BY model ORDER BY SUM(cost_usd) DESC",
            (month,),
        ).fetchall()
        for model, calls, i, o, r, w, cost, unpriced in rows:
            m = {"calls": calls, "input": i or 0, "output": o or 0, "cache_read": r or 0, "cache_write": w or 0, "cost_usd": cost or 0.0, "unpriced_calls": unpriced or 0}
            s["by_model"][model] = m
            for k in ("calls", "input", "output", "cache_read", "cache_write", "cost_usd", "unpriced_calls"):
                s[k] += m[k]
        s["total_input"] = s["input"] + s["cache_read"] + s["cache_write"]
        return s

    def months(self, limit: int = 12) -> list[dict[str, Any]]:
        """記録のある月を新しい順に（今月は記録が無くても先頭に含める）。"""
        names = [r[0] for r in self.conn.execute("SELECT DISTINCT month FROM api_calls ORDER BY month DESC LIMIT ?", (limit,)).fetchall()]
        cur = current_month()
        if cur not in names:
            names.insert(0, cur)
        return [self.month_summary(m) for m in names[:limit]]

    def total_calls(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0])

    # ---- 過去セッションの取り込み ----
    def backfill_from_sessions(self, store: Any, model: str) -> int:
        """台帳を導入する前のセッション（turns[*].usage）を 1 回だけ取り込む。戻り値: 取り込んだ件数。"""
        if self.conn.execute("SELECT value FROM meta WHERE key = 'backfilled'").fetchone():
            return 0
        n = 0
        for item in store.list():
            s = store.get(item["id"])
            if s is None:
                continue
            for t in s.turns:
                if t.get("role") == "assistant" and t.get("usage"):
                    self.record_dict(t["usage"], model, "session", s.id, float(t.get("ts") or s.updated_at or time.time()))
                    n += 1
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('backfilled', ?)", (str(time.time()),))
        return n

    def close(self) -> None:
        self.conn.close()


def month_view(ledger: UsageLedger, usd_jpy: float, budget_usd: float, month: str | None = None) -> dict[str, Any]:
    """ヘッダー表示用の小さな要約。"""
    s = ledger.month_summary(month)
    cost = s["cost_usd"]
    return {
        "month": s["month"],
        "calls": s["calls"],
        "cost_usd": round(cost, 4),
        "cost_jpy": round(cost * usd_jpy),
        "budget_usd": budget_usd,
        "over_budget": bool(budget_usd and cost > budget_usd),
    }


def format_table(months: list[dict[str, Any]], usd_jpy: float) -> str:
    lines = [f"{'月':<8}{'回数':>6}{'入力':>12}{'ｷｬｯｼｭ読':>12}{'出力':>10}{'概算USD':>10}{'概算JPY':>10}"]
    for m in months:
        lines.append(f"{m['month']:<8}{m['calls']:>6}{m['input'] + m['cache_write']:>12,}{m['cache_read']:>12,}{m['output']:>10,}{m['cost_usd']:>10.2f}{round(m['cost_usd'] * usd_jpy):>10,}")
    lines.append(f"（1 USD = {usd_jpy:g} 円で換算。{NOTE}）")
    return "\n".join(lines)
