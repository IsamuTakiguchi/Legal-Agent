"""リサーチメモの Markdown 出力。"""
from __future__ import annotations

import re
import time
from pathlib import Path

from ..models import Hit


def _slug(title: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\s]+", "_", title.strip())
    return s[:60] or "memo"


def save_memo(memos_dir: Path, title: str, markdown: str, hits: dict[str, Hit] | None = None) -> Path:
    from ..agent.citations import citations_footer, resolve_citations

    memos_dir = Path(memos_dir)
    memos_dir.mkdir(parents=True, exist_ok=True)
    body, cites = resolve_citations(markdown, hits or {})
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = memos_dir / f"{stamp}-{_slug(title)}.md"
    content = f"# {title}\n\n作成: {time.strftime('%Y-%m-%d %H:%M')}\n\n{body}\n{citations_footer(cites)}\n"
    path.write_text(content, encoding="utf-8")
    return path
