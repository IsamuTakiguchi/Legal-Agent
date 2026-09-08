"""全ソース共通のデータモデル。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Kind = Literal["case", "book"]


@dataclass
class Hit:
    """検索結果 1 件。`ref` は回答内で引用する安定 ID（例: courts:96174, local:ab12cd:p45）。"""

    ref: str
    source: str
    kind: Kind
    title: str
    subtitle: str = ""
    snippet: str = ""
    url: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_tool_text(self) -> str:
        """Claude に渡す 1 行表現。"""
        parts = [f"[ref={self.ref}] {self.title}"]
        if self.subtitle:
            parts.append(self.subtitle)
        if self.snippet:
            parts.append("抜粋: " + self.snippet.replace("\n", " "))
        return "\n  ".join(parts)


@dataclass
class Document:
    """本文取得結果。`text` は要求範囲の本文、`total_chars` は全体長。"""

    ref: str
    source: str
    kind: Kind
    title: str
    text: str
    url: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    offset: int = 0
    total_chars: int = 0

    def to_tool_text(self) -> str:
        header = [f"[ref={self.ref}] {self.title}"]
        for k, v in self.meta.items():
            if v:
                header.append(f"{k}: {v}")
        if self.url:
            header.append(f"URL: {self.url}")
        end = self.offset + len(self.text)
        if self.total_chars > end:
            header.append(f"（本文 {self.offset}〜{end} 字 / 全 {self.total_chars} 字。続きは offset={end} で取得）")
        else:
            header.append(f"（本文 {self.offset}〜{end} 字 / 全 {self.total_chars} 字。以上で末尾）")
        return "\n".join(header) + "\n---\n" + self.text


@dataclass
class Citation:
    number: int
    hit: Hit

    def to_dict(self) -> dict[str, Any]:
        return {"number": self.number, **self.hit.to_dict()}


class LoginRequired(Exception):
    """ログイン必須サイトで未ログイン／セッション切れのときに送出する。"""

    def __init__(self, site: str, message: str = ""):
        self.site = site
        super().__init__(message or f"{site} にログインが必要です")
