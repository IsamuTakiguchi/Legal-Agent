"""初回セットアップ（対話式）。.env の生成、Chromium の導入、初回索引までを 1 コマンドで行う。"""
from __future__ import annotations

import getpass
import os
import subprocess
import sys
from pathlib import Path

ENV_PATH = Path(".env")


def _ask(prompt: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        v = (getpass.getpass(f"{prompt}{suffix}: ") if secret else input(f"{prompt}{suffix}: ")).strip()
    except EOFError:
        v = ""
    return v or default


def _yes(prompt: str, default: bool = True) -> bool:
    v = _ask(prompt + (" (Y/n)" if default else " (y/N)"), "")
    if not v:
        return default
    return v.lower().startswith("y")


def _read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _write_env(path: Path, env: dict[str, str]) -> None:
    lines = ["# Legal-Agent 設定（setup で生成。手で編集してもよい）"]
    for k, v in env.items():
        lines.append(f"{k}={v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def run_setup(non_interactive: bool = False) -> None:
    print("=== Legal-Agent セットアップ ===")
    env = _read_env(ENV_PATH)
    if not non_interactive:
        env["ANTHROPIC_API_KEY"] = _ask("Anthropic API キー", env.get("ANTHROPIC_API_KEY", ""), secret=True)
        env["LEGAL_AGENT_PDF_DIRS"] = _ask("書籍 PDF のフォルダ（複数はカンマ区切り。無ければ空）", env.get("LEGAL_AGENT_PDF_DIRS", ""))
        sites = []
        if env.get("LEGAL_AGENT_TKC_ENABLED", "").lower() == "true":
            sites.append(("tkc", "TKC ローライブラリー"))
        if env.get("LEGAL_AGENT_LEGAL_LIBRARY_ENABLED", "").lower() == "true":
            sites.append(("legal_library", "LEGAL LIBRARY"))
        if len(sites) < 2:
            print("\n※ TKC ローライブラリー / LEGAL LIBRARY は利用規約の確認結果（docs/TERMS_REVIEW.md）を踏まえ保留中で、アプリからはアクセスしません。")
            print("  利用する場合は .env に LEGAL_AGENT_TKC_ENABLED=true / LEGAL_AGENT_LEGAL_LIBRARY_ENABLED=true を追加して setup をやり直してください。")
        if sites:
            print("\n契約サービスの自動ログイン設定（ID/パスワードは .env に保存されます。空にすれば手動ログイン）")
        for site, label in sites:
            if _yes(f"{label} を使いますか？", True):
                uk, pk = f"LEGAL_AGENT_{site.upper()}_USER", f"LEGAL_AGENT_{site.upper()}_PASSWORD"
                env[uk] = _ask(f"  {label} のログイン ID", env.get(uk, ""))
                env[pk] = _ask(f"  {label} のパスワード", env.get(pk, ""), secret=True)
        env.setdefault("LEGAL_AGENT_MODEL", "claude-opus-5")
        env.setdefault("LEGAL_AGENT_EFFORT", "high")
    env.setdefault("LEGAL_AGENT_DATA_DIR", "./data")
    _write_env(ENV_PATH, env)
    print(f"\n.env を書きました: {ENV_PATH.resolve()}")

    # Chromium
    try:
        print("Chromium を準備しています（初回のみ、数分かかることがあります）…")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
    except Exception as e:  # noqa: BLE001
        print(f"Chromium の導入に失敗しました（後で `playwright install chromium` を実行してください）: {e}")

    # 初回索引
    pdf_dirs = env.get("LEGAL_AGENT_PDF_DIRS", "")
    if pdf_dirs:
        for k, v in env.items():
            os.environ.setdefault(k, v)
        from .config import get_settings
        from .index.db import IndexDB
        from .index.indexer import index_dirs

        s = get_settings()
        print("書籍 PDF を索引化しています…")
        st = index_dirs(IndexDB(s.db_path), s.pdf_dirs)
        print(f"索引: {st['documents']} 冊 / {st['pages']} ページ（追加 {st['added']} / 失敗 {st['failed']}）")
    print("\n完了。`python -m legal_agent` で起動します（ブラウザが自動で開きます）。")
