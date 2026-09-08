"""ローカル書籍 PDF の全文索引（SQLite FTS5）。

日本語は分かち書きできないため、本文を「文字バイグラム列」に変換して FTS5（unicode61）に格納する。
例: 「労働契約」→ "労働 働契 契約"。検索語も同じ変換をしてフレーズ検索する。
これにより SQLite のバージョンに依存せず、2 文字以上の語を安定して検索できる。
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_CJK = r"぀-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ"
_TOKEN_RE = re.compile(rf"[{_CJK}]+|[A-Za-z0-9_]+")
_WS_RE = re.compile(r"\s+")


def to_bigrams(text: str) -> str:
    """索引用にテキストをバイグラム列へ変換する。英数字語はそのまま残す。"""
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0)
        if tok[0].isascii():
            out.append(tok.lower())
        elif len(tok) == 1:
            out.append(tok)
        else:
            out.extend(tok[i : i + 2] for i in range(len(tok) - 1))
    return " ".join(out)


def query_to_match(query: str) -> tuple[str, list[str]]:
    """検索文字列を FTS5 MATCH 式へ変換する。

    戻り値: (MATCH 式, 事後フィルタ用の 1 文字語リスト)
    複数語はスペース区切りで AND 検索。
    """
    phrases: list[str] = []
    singles: list[str] = []
    for term in _WS_RE.split(query.strip()):
        if not term:
            continue
        for m in _TOKEN_RE.finditer(term):
            tok = m.group(0)
            if tok[0].isascii():
                phrases.append(f'"{tok.lower()}"')
            elif len(tok) == 1:
                singles.append(tok)
            else:
                grams = " ".join(tok[i : i + 2] for i in range(len(tok) - 1))
                phrases.append(f'"{grams}"')
    return " AND ".join(phrases), singles


@dataclass
class PageHit:
    doc_id: str
    page_no: int
    title: str
    author: str
    path: str
    text: str
    score: float


SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    publisher TEXT NOT NULL DEFAULT '',
    page_count INTEGER NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    indexed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS pages (
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (doc_id, page_no)
);
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    doc_id UNINDEXED, page_no UNINDEXED, grams, tokenize = 'unicode61'
);
"""


class IndexDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    # ---- 書き込み ----
    def get_document(self, doc_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()

    def find_by_path(self, path: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM documents WHERE path=?", (path,)).fetchone()

    def delete_document(self, doc_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM pages_fts WHERE doc_id=?", (doc_id,))
            self.conn.execute("DELETE FROM pages WHERE doc_id=?", (doc_id,))
            self.conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))

    def add_document(
        self,
        doc_id: str,
        path: str,
        title: str,
        author: str,
        publisher: str,
        mtime: float,
        size: int,
        pages: Iterable[tuple[int, str]],
    ) -> int:
        pages = list(pages)
        with self.conn:
            self.delete_document(doc_id)
            self.conn.execute(
                "INSERT INTO documents (id, path, title, author, publisher, page_count, mtime, size)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (doc_id, path, title, author, publisher, len(pages), mtime, size),
            )
            self.conn.executemany(
                "INSERT INTO pages (doc_id, page_no, text) VALUES (?,?,?)",
                [(doc_id, n, t) for n, t in pages],
            )
            self.conn.executemany(
                "INSERT INTO pages_fts (doc_id, page_no, grams) VALUES (?,?,?)",
                [(doc_id, n, to_bigrams(t)) for n, t in pages if t.strip()],
            )
        return len(pages)

    # ---- 読み取り ----
    def stats(self) -> dict:
        d = self.conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(page_count),0) AS p FROM documents").fetchone()
        return {"documents": d["n"], "pages": d["p"], "db_path": str(self.path)}

    def list_documents(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM documents ORDER BY title").fetchall()

    def get_pages(self, doc_id: str, page_no: int, span: int = 0) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT page_no, text FROM pages WHERE doc_id=? AND page_no BETWEEN ? AND ? ORDER BY page_no",
            (doc_id, max(1, page_no - span), page_no + span),
        ).fetchall()

    def search(self, query: str, limit: int = 20, doc_id: str | None = None) -> list[PageHit]:
        match, singles = query_to_match(query)
        rows: list[sqlite3.Row]
        if match:
            sql = (
                "SELECT f.doc_id, f.page_no, bm25(pages_fts) AS score, d.title, d.author, d.path, p.text"
                " FROM pages_fts f JOIN documents d ON d.id=f.doc_id"
                " JOIN pages p ON p.doc_id=f.doc_id AND p.page_no=f.page_no"
                " WHERE pages_fts MATCH ?"
            )
            params: list = [match]
            if doc_id:
                sql += " AND f.doc_id=?"
                params.append(doc_id)
            sql += " ORDER BY score LIMIT ?"
            params.append(limit * 3 if singles else limit)
            rows = self.conn.execute(sql, params).fetchall()
        elif singles:
            # 1 文字語のみ: LIKE 検索にフォールバック
            like = " AND ".join("p.text LIKE ?" for _ in singles)
            sql = (
                "SELECT p.doc_id, p.page_no, 0.0 AS score, d.title, d.author, d.path, p.text"
                f" FROM pages p JOIN documents d ON d.id=p.doc_id WHERE {like}"
            )
            params = [f"%{s}%" for s in singles]
            if doc_id:
                sql += " AND p.doc_id=?"
                params.append(doc_id)
            sql += " LIMIT ?"
            params.append(limit)
            rows = self.conn.execute(sql, params).fetchall()
        else:
            return []
        hits: list[PageHit] = []
        for r in rows:
            if singles and not all(s in r["text"] for s in singles):
                continue
            hits.append(PageHit(r["doc_id"], r["page_no"], r["title"], r["author"], r["path"], r["text"], r["score"]))
            if len(hits) >= limit:
                break
        return hits


def make_snippet(text: str, query: str, width: int = 160) -> str:
    """検索語の最初の出現位置を中心に抜粋を作る。"""
    flat = _WS_RE.sub(" ", text)
    terms = [t for t in _WS_RE.split(query) if t]
    pos = -1
    for t in terms:
        i = flat.find(t)
        if i >= 0 and (pos < 0 or i < pos):
            pos = i
    if pos < 0:
        return flat[:width]
    start = max(0, pos - width // 3)
    return ("…" if start > 0 else "") + flat[start : start + width] + ("…" if start + width < len(flat) else "")
