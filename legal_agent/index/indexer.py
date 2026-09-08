"""PDF フォルダを走査して索引を差分更新する。"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Callable, Iterable

import pymupdf

from .db import IndexDB


def doc_id_for(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12]


def guess_title(path: Path, meta: dict) -> tuple[str, str]:
    """PDF メタデータとファイル名から (書名, 著者) を推定する。"""
    title = (meta.get("title") or "").strip()
    author = (meta.get("author") or "").strip()
    stem = path.stem
    # ファイル名が「著者_書名」「書名（著者）」のような形なら分解
    if not title:
        m = re.match(r"^(.+?)[_＿]\s*(.+)$", stem)
        if m and not author:
            author, title = m.group(1).strip(), m.group(2).strip()
        else:
            title = stem
    if not title or title.lower() in {"untitled", "microsoft word"}:
        title = stem
    return title, author


def extract_pages(path: Path) -> tuple[dict, list[tuple[int, str]]]:
    with pymupdf.open(str(path)) as doc:
        meta = doc.metadata or {}
        pages = []
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            pages.append((i, text))
    return meta, pages


def iter_pdfs(dirs: Iterable[Path]) -> Iterable[Path]:
    for d in dirs:
        d = Path(d)
        if d.is_file() and d.suffix.lower() == ".pdf":
            yield d
        elif d.is_dir():
            yield from sorted(p for p in d.rglob("*.pdf") if p.is_file())


def index_dirs(
    db: IndexDB,
    dirs: Iterable[Path],
    rebuild: bool = False,
    log: Callable[[str], None] = lambda s: print(s, file=sys.stderr),
) -> dict:
    added = skipped = failed = 0
    seen: set[str] = set()
    for pdf in iter_pdfs(dirs):
        doc_id = doc_id_for(pdf)
        seen.add(doc_id)
        st = pdf.stat()
        existing = db.get_document(doc_id)
        if existing and not rebuild and existing["mtime"] == st.st_mtime and existing["size"] == st.st_size:
            skipped += 1
            continue
        try:
            meta, pages = extract_pages(pdf)
            title, author = guess_title(pdf, meta)
            n = db.add_document(doc_id, str(pdf.resolve()), title, author, "", st.st_mtime, st.st_size, pages)
            added += 1
            log(f"索引: {title} ({n} ページ) <- {pdf}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            log(f"失敗: {pdf}: {e}")
    # 削除されたファイルを索引から除く
    removed = 0
    for row in db.list_documents():
        if row["id"] not in seen and not Path(row["path"]).exists():
            db.delete_document(row["id"])
            removed += 1
    return {"added": added, "skipped": skipped, "failed": failed, "removed": removed, **db.stats()}
