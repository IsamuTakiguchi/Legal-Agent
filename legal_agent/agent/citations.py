"""回答中の [[ref]] マーカーを番号付き引用に変換し、Hit と突合する。"""
from __future__ import annotations

import re

from ..models import Citation, Hit

REF_RE = re.compile(r"\[\[\s*([a-z_]+:[^\]\s]+?)\s*\]\]")


def resolve_citations(text: str, hits: dict[str, Hit]) -> tuple[str, list[Citation]]:
    order: dict[str, int] = {}
    cites: list[Citation] = []

    def repl(m: re.Match) -> str:
        ref = m.group(1)
        hit = hits.get(ref)
        if hit is None:
            # 検索していない ref を捏造した場合は明示する
            return f"[出典不明: {ref}]"
        if ref not in order:
            order[ref] = len(order) + 1
            cites.append(Citation(number=order[ref], hit=hit))
        return f"[{order[ref]}]"

    new_text = REF_RE.sub(repl, text)
    return new_text, cites


def citations_footer(cites: list[Citation]) -> str:
    if not cites:
        return ""
    lines = ["", "出典:"]
    for c in cites:
        h = c.hit
        line = f"[{c.number}] {h.title}"
        if h.subtitle:
            line += f"（{h.subtitle}）"
        if h.url:
            line += f" {h.url}"
        lines.append(line)
    return "\n".join(lines)
