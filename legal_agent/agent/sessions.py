"""チャットセッション（会話履歴と引用）の保存。data/sessions/{id}.json"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ChatSession:
    id: str
    title: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list[dict[str, Any]] = field(default_factory=list)  # API に渡す形式そのまま
    turns: list[dict[str, Any]] = field(default_factory=list)  # UI 表示用 {role, text, citations}
    hits: dict[str, dict[str, Any]] = field(default_factory=dict)  # ref → Hit dict（引用解決用）

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "created_at": self.created_at, "updated_at": self.updated_at,
            "messages": self.messages, "turns": self.turns, "hits": self.hits,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ChatSession":
        return cls(**{k: d.get(k, v) for k, v in cls(id="").__dict__.items()} | {"id": d["id"]})


class SessionStore:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, ChatSession] = {}

    def _path(self, sid: str) -> Path:
        return self.dir / f"{sid}.json"

    def create(self) -> ChatSession:
        s = ChatSession(id=uuid.uuid4().hex[:12])
        self._cache[s.id] = s
        self.save(s)
        return s

    def get(self, sid: str) -> ChatSession | None:
        if sid in self._cache:
            return self._cache[sid]
        p = self._path(sid)
        if not p.exists():
            return None
        s = ChatSession.from_dict(json.loads(p.read_text(encoding="utf-8")))
        self._cache[sid] = s
        return s

    def get_or_create(self, sid: str | None) -> ChatSession:
        return (self.get(sid) if sid else None) or self.create()

    def save(self, s: ChatSession) -> None:
        s.updated_at = time.time()
        self._path(s.id).write_text(json.dumps(s.to_dict(), ensure_ascii=False), encoding="utf-8")

    def list(self) -> list[dict[str, Any]]:
        out = []
        for p in sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                out.append({"id": d["id"], "title": d.get("title") or "(無題)", "updated_at": d.get("updated_at", 0), "turns": len(d.get("turns", []))})
            except Exception:  # noqa: BLE001
                continue
        return out

    def delete(self, sid: str) -> bool:
        self._cache.pop(sid, None)
        p = self._path(sid)
        if p.exists():
            p.unlink()
            return True
        return False
