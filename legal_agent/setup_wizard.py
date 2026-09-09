"""セットアップ処理。

- ブラウザ版（既定）: サーバー起動後、API キー未設定なら画面にセットアップパネルが出る（app.py の /api/setup）。
- ターミナル版: `python -m legal_agent setup`。
どちらも `apply_setup()` で .env を書き、プロセス内の環境変数にも反映する。
"""
from __future__ import annotations

import asyncio
import getpass
import os
import subprocess
import sys
from pathlib import Path

ENV_PATH = Path(".env")
API_KEY_URL = "https://console.anthropic.com/settings/keys"


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


def read_env(path: Path = ENV_PATH) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def write_env(path: Path, env: dict[str, str]) -> None:
    lines = ["# Legal-Agent 設定（セットアップで生成。手で編集してもよい）"]
    for k, v in env.items():
        lines.append(f"{k}={v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# 互換
_read_env = read_env
_write_env = write_env


def login_sites_enabled(env: dict[str, str]) -> bool:
    return any(env.get(k, "").lower() == "true" for k in ("LEGAL_AGENT_TKC_ENABLED", "LEGAL_AGENT_LEGAL_LIBRARY_ENABLED"))


def apply_setup(api_key: str | None, pdf_dirs: list[str] | None, env_path: Path = ENV_PATH) -> dict[str, str]:
    """.env を更新し、プロセス内の環境変数にも反映する。None の項目は変更しない。"""
    env = read_env(env_path)
    if api_key is not None and api_key.strip():
        env["ANTHROPIC_API_KEY"] = api_key.strip()
    if pdf_dirs is not None:
        env["LEGAL_AGENT_PDF_DIRS"] = ",".join(str(p) for p in pdf_dirs if str(p).strip())
    env.setdefault("LEGAL_AGENT_MODEL", "claude-opus-5")
    env.setdefault("LEGAL_AGENT_EFFORT", "high")
    env.setdefault("LEGAL_AGENT_DATA_DIR", "./data")
    write_env(env_path, env)
    if env.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = env["ANTHROPIC_API_KEY"]
    os.environ["LEGAL_AGENT_PDF_DIRS"] = env.get("LEGAL_AGENT_PDF_DIRS", "")
    return env


async def validate_api_key(api_key: str, timeout: float = 15.0) -> str | None:
    """API キーで Claude API に到達できるか確認する。問題なければ None、失敗なら理由を返す。"""
    import anthropic

    key = (api_key or "").strip()
    if not key:
        return "API キーが空です"
    try:
        client = anthropic.AsyncAnthropic(api_key=key, timeout=timeout, max_retries=0)
        await client.models.list(limit=1)
        return None
    except anthropic.AuthenticationError:
        return "API キーが正しくありません（認証エラー）"
    except anthropic.PermissionDeniedError:
        return "この API キーには権限がありません"
    except anthropic.APIConnectionError as e:
        return f"Claude API に接続できません（ネットワークを確認してください）: {e}"
    except anthropic.APIStatusError as e:
        return f"Claude API エラー {e.status_code}: {e.message}"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"


def install_chromium_if_needed(env: dict[str, str], out=print) -> None:
    """TKC / LEGAL LIBRARY が有効なときだけ Chromium を用意する（保留中は不要）。"""
    if not login_sites_enabled(env):
        return
    try:
        out("Chromium を準備しています（初回のみ、数分かかることがあります）…")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
    except Exception as e:  # noqa: BLE001
        out(f"Chromium の導入に失敗しました（後で `playwright install chromium` を実行してください）: {e}")


def choose_pdf_dirs(current: str = "", ask=_ask, out=print) -> str:
    """OneDrive の同期フォルダを検出し、PDF を含むフォルダを番号で選ばせる。見つからなければ手入力。"""
    from .onedrive import describe_dir, detect_onedrive_roots, list_pdf_folders, strip_quotes

    candidates: list[tuple[Path, int]] = []
    for root in detect_onedrive_roots():
        candidates.extend(list_pdf_folders(root))
    chosen: list[Path] = []
    if candidates:
        out("\n書籍 PDF のフォルダ（OneDrive 内で PDF が見つかったフォルダ）:")
        for i, (p, n) in enumerate(candidates, start=1):
            out(f"  {i:2d}. {p}（PDF {n} 件）")
        out("   0. 別のフォルダをパスで指定する")
        raw = ask("番号を入力（複数はカンマ区切り）", current or "1")
        nums = [s.strip() for s in raw.replace("，", ",").split(",") if s.strip()]
        if all(s.isdigit() for s in nums) and nums and nums != ["0"]:
            for s in nums:
                i = int(s)
                if 1 <= i <= len(candidates):
                    chosen.append(candidates[i - 1][0])
        elif nums and not all(s.isdigit() for s in nums):
            chosen = [Path(strip_quotes(s)).expanduser() for s in raw.split(",") if strip_quotes(s)]
    if not chosen:
        raw = ask("書籍 PDF のフォルダをパスで入力（複数はカンマ区切り。無ければ空）", current)
        chosen = [Path(strip_quotes(s)).expanduser() for s in raw.split(",") if strip_quotes(s)]
    for p in chosen:
        info = describe_dir(p)
        if not info["exists"]:
            out(f"  注意: {p} が見つかりません（OneDrive にサインインしているか確認してください）")
        else:
            note = f"、うちクラウドのみ {info['cloud_only']} 件（許可した PDF だけ索引時にダウンロードします）" if info["cloud_only"] else ""
            out(f"  {p}: PDF {info['pdfs']} 件{note}")
    return ",".join(str(p) for p in chosen)


def run_setup(non_interactive: bool = False) -> None:
    """ターミナル版セットアップ。"""
    print("=== Legal-Agent セットアップ ===")
    env = read_env(ENV_PATH)
    api_key = None
    pdf_dirs = None
    if not non_interactive:
        print(f"API キーは {API_KEY_URL} で発行できます。")
        api_key = _ask("Anthropic API キー", env.get("ANTHROPIC_API_KEY", ""), secret=True)
        pdf_dirs = choose_pdf_dirs(env.get("LEGAL_AGENT_PDF_DIRS", "")).split(",")
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
                write_env(ENV_PATH, env)
    if api_key:
        err = asyncio.run(validate_api_key(api_key))
        print("API キーを確認しました。" if err is None else f"注意: {err}")
    env = apply_setup(api_key, pdf_dirs, ENV_PATH)
    print(f"\n.env を書きました: {ENV_PATH.resolve()}")
    install_chromium_if_needed(env)

    # 初回索引
    if env.get("LEGAL_AGENT_PDF_DIRS"):
        from .config import get_settings
        from .index.db import IndexDB
        from .index.indexer import index_dirs

        get_settings.cache_clear()
        s = get_settings()
        print("書籍 PDF を索引化しています…")
        st = index_dirs(IndexDB(s.db_path), s.pdf_dirs)
        print(f"索引: {st['documents']} 冊 / {st['pages']} ページ（追加 {st['added']} / 失敗 {st['failed']}）")
    print("\n完了。`python -m legal_agent`（または start.bat）で起動します（ブラウザが自動で開きます）。")
