"""アプリ設定。`.env` と環境変数（接頭辞 LEGAL_AGENT_）から読み込む。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LEGAL_AGENT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    model: str = "claude-opus-5"
    effort: str = "high"
    max_tokens: int = 64000
    # Claude Opus 5 / Fable のポリシー拒否時にサーバ側で別モデルへ切替（beta）
    fallbacks_enabled: bool = True

    pdf_dirs: list[Path] = Field(default_factory=list)
    data_dir: Path = Path("./data")

    host: str = "127.0.0.1"
    port: int = 8765

    headless: bool = True
    debug_dump: bool = False
    # 通常は空（playwright install chromium のものを使う）。別の Chromium を使う場合のみ指定
    chromium_path: str = ""

    # 自動ログイン用の認証情報（未設定なら手動ログイン）
    tkc_user: str = ""
    tkc_password: str = ""
    legal_library_user: str = ""
    legal_library_password: str = ""

    # 起動時の自動処理
    auto_index: bool = True
    auto_login: bool = True
    auto_open_browser: bool = True
    # Claude によるセレクタ自動発見（ログイン後の画面構造を解析して data/selectors.override.yaml に保存）
    auto_configure: bool = True
    autoconf_model: str = "claude-opus-5"

    max_searches_per_source: int = 3
    max_fetches_per_run: int = 6
    min_interval_sec: float = 1.0

    # 1 回のツール呼び出しで返す本文の最大文字数（続きは offset で取得）
    max_text_chars: int = 12000

    @field_validator("pdf_dirs", mode="before")
    @classmethod
    def _split_dirs(cls, v):
        if isinstance(v, str):
            return [Path(p.strip()).expanduser() for p in v.split(",") if p.strip()]
        return v

    # 派生パス
    @property
    def db_path(self) -> Path:
        return self.data_dir / "index.sqlite3"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def memos_dir(self) -> Path:
        return self.data_dir / "memos"

    @property
    def debug_dir(self) -> Path:
        return self.data_dir / "debug"

    @property
    def browser_profile_dir(self) -> Path:
        return self.data_dir / "browser_profile"

    @property
    def selectors_override_path(self) -> Path:
        return self.data_dir / "selectors.override.yaml"

    def credentials(self, site: str) -> tuple[str, str]:
        return getattr(self, f"{site}_user", ""), getattr(self, f"{site}_password", "")

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.cache_dir, self.sessions_dir, self.memos_dir, self.browser_profile_dir):
            p.mkdir(parents=True, exist_ok=True)
        if self.debug_dump:
            self.debug_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
