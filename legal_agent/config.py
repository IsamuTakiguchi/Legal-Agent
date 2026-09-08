"""アプリ設定。`.env` と環境変数（接頭辞 LEGAL_AGENT_）から読み込む。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LEGAL_AGENT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Anthropic API キー。接頭辞なしの ANTHROPIC_API_KEY を環境変数と .env の両方から読む
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")

    model: str = "claude-opus-5"
    effort: str = "high"
    max_tokens: int = 64000
    # Claude Opus 5 / Fable のポリシー拒否時にサーバ側で別モデルへ切替（beta）
    fallbacks_enabled: bool = True

    # 環境変数はカンマ区切りの文字列（JSON ではない）。NoDecode で自前の分割に任せる
    pdf_dirs: Annotated[list[Path], NoDecode] = Field(default_factory=list)
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

    # 契約サービスは利用規約の確認結果（docs/TERMS_REVIEW.md）を踏まえ、既定で「保留」。
    # 保留中はアプリからサイトへ一切アクセスせず、利用者が自分で検索するためのリンクを案内するだけになる。
    # - LEGAL LIBRARY: 第 8 条で自動化手段によるアクセス・AI 等の使用を明文で禁止。運営会社の許諾を得た場合のみ true
    # - TKC ローライブラリー: 明文禁止はないが 9-1（複製・目的外利用）との関係と個別規約が未確認。確認後に true
    tkc_enabled: bool = False
    legal_library_enabled: bool = False

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

    # セットアップ画面が書き込む .env の場所（カレントディレクトリ。start.bat はリポジトリ直下で起動する）
    env_path: Path = Path(".env")

    def credentials(self, site: str) -> tuple[str, str]:
        return getattr(self, f"{site}_user", ""), getattr(self, f"{site}_password", "")

    def export_api_key(self) -> None:
        """.env から読んだ API キーを SDK が読む環境変数へ反映する。"""
        if self.anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = self.anthropic_api_key

    @property
    def needs_setup(self) -> bool:
        """API キーがどこにも無ければ、ブラウザ上のセットアップ画面を出す。"""
        if self.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return False
        return not sdk_has_credentials()

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.cache_dir, self.sessions_dir, self.memos_dir, self.browser_profile_dir):
            p.mkdir(parents=True, exist_ok=True)
        if self.debug_dump:
            self.debug_dir.mkdir(parents=True, exist_ok=True)


def sdk_has_credentials() -> bool:
    """`ant auth login` のプロファイル等、SDK 側で資格情報を解決できるか。"""
    try:
        import anthropic

        c = anthropic.Anthropic()
        return bool(getattr(c, "api_key", None) or getattr(c, "auth_token", None))
    except Exception:  # noqa: BLE001
        return False


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    s.export_api_key()
    return s
