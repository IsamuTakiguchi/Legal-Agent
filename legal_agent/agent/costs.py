"""トークン使用量の集計・概算料金・履歴の圧縮。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# 1M トークンあたり USD: (入力, 出力, キャッシュ読み, キャッシュ書き 5 分)
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5": (5.0, 25.0, 0.5, 6.25),
    "claude-opus-4-8": (5.0, 25.0, 0.5, 6.25),
    "claude-opus-4-7": (5.0, 25.0, 0.5, 6.25),
    "claude-sonnet-5": (2.0, 10.0, 0.2, 2.5),
    "claude-sonnet-4-6": (3.0, 15.0, 0.3, 3.75),
    "claude-haiku-4-5": (1.0, 5.0, 0.1, 1.25),
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5),
    "claude-fable-5": (10.0, 50.0, 1.0, 12.5),
}


def price_for(model: str) -> tuple[float, float, float, float] | None:
    for k, v in PRICES.items():
        if model.startswith(k):
            return v
    return None


@dataclass
class UsageTotals:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    turns: int = 0

    def add(self, usage: Any) -> None:
        if usage is None:
            return
        self.input += int(getattr(usage, "input_tokens", 0) or 0)
        self.output += int(getattr(usage, "output_tokens", 0) or 0)
        self.cache_read += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        self.cache_write += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        self.turns += 1

    def add_dict(self, d: dict[str, Any] | None) -> None:
        if not d:
            return
        self.input += int(d.get("input", 0))
        self.output += int(d.get("output", 0))
        self.cache_read += int(d.get("cache_read", 0))
        self.cache_write += int(d.get("cache_write", 0))
        self.turns += int(d.get("turns", 0))

    def cost_usd(self, model: str) -> float | None:
        p = price_for(model)
        if p is None:
            return None
        i, o, r, w = p
        return (self.input * i + self.output * o + self.cache_read * r + self.cache_write * w) / 1_000_000

    def to_dict(self, model: str | None = None) -> dict[str, Any]:
        d = asdict(self)
        d["total_input"] = self.input + self.cache_read + self.cache_write
        if model:
            d["cost_usd"] = self.cost_usd(model)
        return d


COMPACT_KEEP_CHARS = 300


def compact_history(messages: list[dict[str, Any]], upto: int) -> int:
    """messages[:upto]（過去の質問のターン）に含まれる長いツール結果を短くし、thinking を落とす。

    戻り値: 圧縮したブロック数。以降のターン（最新の質問）は触らない。
    """
    changed = 0
    for m in messages[:upto]:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        new_content = []
        for b in content:
            if not isinstance(b, dict):
                new_content.append(b)
                continue
            t = b.get("type")
            if t in ("thinking", "redacted_thinking"):
                changed += 1
                continue
            if t == "tool_result":
                text = b.get("content")
                if isinstance(text, list):  # ブロック形式 → テキストを連結
                    text = "".join(x.get("text", "") for x in text if isinstance(x, dict))
                if isinstance(text, str) and len(text) > COMPACT_KEEP_CHARS + 60 and not b.get("_compacted"):
                    head = text[:COMPACT_KEEP_CHARS]
                    b = {**b, "content": f"{head}\n（省略: 全 {len(text)} 字。前の質問で取得済み。必要なら再取得）", "_compacted": True}
                    changed += 1
            new_content.append(b)
        if not new_content:  # thinking しか無かった assistant ブロックは空にできないので最小テキストを置く
            new_content = [{"type": "text", "text": "（省略）"}]
        m["content"] = new_content
    return changed


def strip_private_keys(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """API に送る直前に内部用キー（_compacted）を除く。"""
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = [{k: v for k, v in b.items() if not k.startswith("_")} if isinstance(b, dict) else b for b in c]
            m = {**m, "content": c}
        out.append(m)
    return out
