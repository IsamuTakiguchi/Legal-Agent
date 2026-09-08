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
            note = f"、うちクラウドのみ {info['cloud_only']} 件（索引時に順次ダウンロードされます）" if info["cloud_only"] else ""
            out(f"  {p}: PDF {info['pdfs']} 件{note}")
    return ",".join(str(p) for p in chosen)


def run_setup(non_interactive: bool = False) -> None:
    print("=== Legal-Agent セットアップ ===")
    env = _read_env(ENV_PATH)
    if not non_interactive:
        env["ANTHROPIC_API_KEY"] = _ask("Anthropic API キー", env.get("ANTHROPIC_API_KEY", ""), secret=True)
        env["LEGAL_AGENT_PDF_DIRS"] = choose_pdf_dirs(env.get("LEGAL_AGENT_PDF_DIRS", ""))
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
