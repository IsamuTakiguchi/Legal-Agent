""".env の自動移行: アプリの既定モデルを新しくしたとき、利用者の .env を追従させる。

初回セットアップは .env に LEGAL_AGENT_MODEL=<その時点の既定> を書き込むため、config.py の既定を
変えるだけでは既存の利用者は古いモデルのまま動き続ける。起動時にここを通して、
「以前のアプリ既定値と完全に一致する」行だけを新しい既定値に書き換える。

- 利用者が自分で選んだ値（別のモデル）は触らない。
- 書き換えるのは該当行の値だけ。API キーを含む他の行・コメント・順序・改行コードはそのまま残す。
- 一時ファイルに書いてから置き換える（途中で落ちても .env が壊れない）。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from .config import Settings

log = logging.getLogger(__name__)

# 過去のアプリ既定値（ここに載っている値だけを最新の既定値へ移行する）
RETIRED_DEFAULTS = {"claude-opus-5"}

# .env のキー → Settings の項目名
MODEL_KEYS = {"LEGAL_AGENT_MODEL": "model", "LEGAL_AGENT_AUTOCONF_MODEL": "autoconf_model"}


def migrate_env(path: Path = Path(".env")) -> list[str]:
    """移行した内容（「キー: 旧 → 新」）の一覧を返す。何もしなければ空。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    try:
        text = raw.decode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8")
    except UnicodeDecodeError:
        return []  # 読めない .env は触らない

    changes: list[str] = []
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        if body.lstrip().startswith("#") or "=" not in body:
            continue
        key, value = body.split("=", 1)
        field = MODEL_KEYS.get(key.strip())
        if field is None or value.strip() not in RETIRED_DEFAULTS:
            continue
        new = Settings.model_fields[field].default
        if value.strip() == new:
            continue
        lines[i] = f"{key}={new}" + line[len(body):]
        changes.append(f"{key.strip()}: {value.strip()} → {new}")

    if not changes:
        return []
    out = "".join(lines).encode("utf-8")
    if raw.startswith(b"\xef\xbb\xbf"):
        out = b"\xef\xbb\xbf" + out
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(out)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except OSError as e:
        log.warning(".env の移行に失敗（そのまま起動します）: %s", e)
        try:
            tmp.unlink()
        except OSError:
            pass
        return []
    for c in changes:
        log.info(".env を更新しました: %s", c)
    return changes
