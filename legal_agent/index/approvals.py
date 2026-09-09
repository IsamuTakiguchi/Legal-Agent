"""OneDrive「クラウドのみ」PDF のダウンロード許可。

ファイル オンデマンドのプレースホルダーを開くと OneDrive が自動でダウンロードするため、
索引作成はそのままでは電子書籍 PDF を勝手に取得してしまう。許可した PDF だけを読むようにする。
許可は data/download_approvals.json に保存し、再スキャンでも引き継ぐ。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def _key(path: Path | str) -> str:
    return str(Path(path).resolve()).lower()


class DownloadApprovals:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.allow_all = False
        self.allowed: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        self.allow_all = bool(d.get("allow_all"))
        self.allowed = {str(p).lower() for p in d.get("allowed", [])}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"allow_all": self.allow_all, "allowed": sorted(self.allowed)}, ensure_ascii=False, indent=1), encoding="utf-8")

    def is_allowed(self, path: Path | str) -> bool:
        return self.allow_all or _key(path) in self.allowed

    def allow(self, paths: Iterable[Path | str]) -> int:
        before = len(self.allowed)
        self.allowed.update(_key(p) for p in paths)
        self.save()
        return len(self.allowed) - before

    def set_allow_all(self, value: bool) -> None:
        self.allow_all = bool(value)
        self.save()

    def revoke(self, paths: Iterable[Path | str]) -> None:
        self.allowed.difference_update(_key(p) for p in paths)
        self.save()
