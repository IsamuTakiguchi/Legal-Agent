"""OneDrive 同期フォルダの検出と、ファイル オンデマンド（クラウドのみ）状態の判定。

Microsoft Graph API は使わない。OneDrive 同期クライアントが PC 上に置くローカルフォルダを通常のパスとして扱う。
"""
from __future__ import annotations

import os
import stat as _stat
import sys
from pathlib import Path

# Windows のファイル属性（stat.FILE_ATTRIBUTE_* は一部しか定義されていないため定数で持つ）
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY_MASK = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", ".tmp"}


def detect_onedrive_roots(env: dict[str, str] | None = None, home: Path | None = None, platform: str | None = None) -> list[Path]:
    """OneDrive のルートフォルダ候補（存在するもの）を優先順に返す。"""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    platform = sys.platform if platform is None else platform
    candidates: list[Path] = []
    if platform.startswith("win"):
        for key in ("OneDriveConsumer", "OneDrive", "OneDriveCommercial"):
            if env.get(key):
                candidates.append(Path(env[key]))
        profile = env.get("USERPROFILE")
        if profile:
            candidates.append(Path(profile) / "OneDrive")
        candidates.append(home / "OneDrive")
    elif platform == "darwin":
        cloud = home / "Library" / "CloudStorage"
        if cloud.is_dir():
            candidates.extend(sorted(p for p in cloud.iterdir() if p.name.startswith("OneDrive")))
        candidates.append(home / "OneDrive")
    else:
        candidates.append(home / "OneDrive")
    out: list[Path] = []
    seen: set[str] = set()
    for c in candidates:
        try:
            if c.is_dir():
                key = str(c.resolve()).lower()
                if key not in seen:
                    seen.add(key)
                    out.append(c)
        except OSError:
            continue
    return out


def _count_pdfs(folder: Path, max_files: int = 5000) -> int:
    n = 0
    stack = [folder]
    while stack and n < max_files:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.name.startswith(".") or e.name.startswith("~$"):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if e.name not in SKIP_DIR_NAMES:
                            stack.append(Path(e.path))
                    elif e.is_file(follow_symlinks=False) and e.name.lower().endswith(".pdf"):
                        n += 1
        except OSError:
            continue
    return n


def list_pdf_folders(root: Path, max_depth: int = 3, limit: int = 30) -> list[tuple[Path, int]]:
    """root 配下で PDF を含むフォルダを (パス, 再帰的な PDF 件数) の一覧で返す。件数の多い順。"""
    root = Path(root)
    found: list[tuple[Path, int]] = []

    def walk(d: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            with os.scandir(d) as it:
                subdirs = [Path(e.path) for e in it if e.is_dir(follow_symlinks=False) and not e.name.startswith(".") and e.name not in SKIP_DIR_NAMES]
        except OSError:
            return
        for sd in sorted(subdirs):
            n = _count_pdfs(sd)
            if n > 0:
                found.append((sd, n))
            walk(sd, depth + 1)

    walk(root, 1)
    # 親フォルダと子フォルダが同じ件数なら（PDF は子にしかない）親を省く
    counts = dict((str(p), n) for p, n in found)
    pruned = []
    for p, n in found:
        children = [c for c in found if c[0].parent == p]
        if len(children) == 1 and children[0][1] == n:
            continue
        pruned.append((p, n))
    pruned.sort(key=lambda x: (-x[1], str(x[0]).lower()))
    _ = counts
    return pruned[:limit]


def is_cloud_only(path: Path | str, platform: str | None = None) -> bool:
    """Windows の OneDrive ファイル オンデマンドで「クラウドのみ」（プレースホルダー）か。"""
    platform = sys.platform if platform is None else platform
    if not platform.startswith("win"):
        return False
    try:
        st = os.stat(path)
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & CLOUD_ONLY_MASK)


def describe_dir(path: Path | str) -> dict:
    """UI 表示用: フォルダの存在・PDF 件数・クラウドのみ件数。"""
    p = Path(path)
    info = {"path": str(p), "exists": p.is_dir(), "pdfs": 0, "cloud_only": 0}
    if not info["exists"]:
        return info
    try:
        for f in p.rglob("*"):
            if f.suffix.lower() != ".pdf" or f.name.startswith("~$") or not f.is_file():
                continue
            info["pdfs"] += 1
            if is_cloud_only(f):
                info["cloud_only"] += 1
            if info["pdfs"] >= 5000:
                break
    except OSError:
        pass
    return info


def strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    return s.strip()


__all__ = [
    "detect_onedrive_roots", "list_pdf_folders", "is_cloud_only", "describe_dir", "strip_quotes",
    "CLOUD_ONLY_MASK", "FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS", "FILE_ATTRIBUTE_OFFLINE",
]
_ = _stat  # 参照保持（将来 stat.FILE_ATTRIBUTE_* に切替可能）
