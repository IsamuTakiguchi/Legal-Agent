"""状態診断（check.bat / `python -m legal_agent doctor`）。どこに入っていて、何ができていて、何が足りないかを日本語で表示する。"""
from __future__ import annotations

import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tail(path: Path, n: int = 15) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


def run_doctor(after_install: bool = False, out=print, file: Path | None = None) -> int:
    """戻り値: 0 = 問題なし、1 = 要対応。file を渡すと UTF-8（BOM 付き、メモ帳向け）にも書き出す。"""
    from .config import get_settings

    lines: list[str] = []
    if file is not None:
        orig_out = out

        def out(msg: str = "") -> None:  # type: ignore[no-redef]
            lines.append(str(msg))
            try:
                orig_out(msg)
            except Exception:  # noqa: BLE001 コンソールの文字コードが合わない場合でも続行
                pass

    try:
        code = _run(after_install, out)
    finally:
        if file is not None:
            try:
                file.parent.mkdir(parents=True, exist_ok=True)
                new = not file.exists() or file.stat().st_size == 0
                with file.open("a", encoding="utf-8") as f:  # 追記（bat が書いたヘッダーを消さない）
                    if new:
                        f.write("\ufeff")
                    f.write("\r\n".join(lines) + "\r\n")
            except OSError:
                pass
    return code


def _run(after_install: bool, out) -> int:
    from .config import get_settings

    problems: list[str] = []
    out("=== Legal-Agent 状態確認 ===")
    out(f"インストール先: {ROOT}")
    out("  （通常は C:\\Users\\<名前>\\AppData\\Local\\Legal-Agent。Program Files 等には入りません）")
    if "onedrive" in str(ROOT).lower():
        problems.append("OneDrive の同期フォルダ内にインストールされています。同期やクラウドのみ化で Python が動かなくなるため、install.bat をもう一度ダブルクリックして AppData\\Local\\Legal-Agent に移してください")
    out(f"Python: {platform.python_version()}  {sys.executable}")
    private = ROOT / "python" / "python.exe"
    if private.exists():
        out(f"アプリ専用 Python: あり ({private})")
    elif (ROOT / ".venv").exists():
        out("Python 環境: .venv（旧方式）")
    else:
        out("Python 環境: 見つかりません（install.bat を実行してください）")
        problems.append("Python 環境がありません。install.bat を実行してください")

    try:
        import anthropic, fastapi, pymupdf  # noqa: F401

        out("ライブラリ: インストール済み（anthropic / fastapi / pymupdf）")
    except Exception as e:  # noqa: BLE001
        out(f"ライブラリ: 不足（{e}）")
        problems.append("ライブラリが足りません。install.bat をもう一度実行するか install.log を確認してください")

    s = get_settings()
    env_path = ROOT / ".env"
    out(f"設定ファイル (.env): {'あり' if env_path.exists() else 'まだ無い（初回起動時にブラウザ画面で作成されます）'}")
    if s.needs_setup:
        out("API キー: 未設定 → 起動後のブラウザ画面で設定してください")
    else:
        out("API キー: 設定済み")
    if s.pdf_dirs:
        for p in s.pdf_dirs:
            out(f"書籍 PDF フォルダ: {p}  {'（見つかりません）' if not p.is_dir() else ''}")
    else:
        out("書籍 PDF フォルダ: 未設定（ブラウザ画面で選べます）")
    try:
        from .index.db import IndexDB

        st = IndexDB(s.db_path).stats()
        out(f"索引: {st['documents']} 冊 / {st['pages']} ページ  ({s.db_path})")
    except Exception as e:  # noqa: BLE001
        out(f"索引: 読めません（{e}）")

    # サーバー稼働確認
    running = False
    try:
        import httpx

        r = httpx.get(f"http://{s.host}:{s.port}/api/status", timeout=2)
        running = r.status_code == 200
    except Exception:  # noqa: BLE001
        running = False
    url = f"http://{s.host}:{s.port}/"
    out(f"サーバー: {'起動中 → ' + url if running else '停止中（start.bat またはデスクトップの Legal-Agent で起動）'}")

    from .shortcut import ensure_shortcut

    out(f"デスクトップのショートカット: {ensure_shortcut(out=out)}")

    upd = ROOT / ".update.json"
    if upd.exists():
        out(f"自動更新の記録: {upd.name} あり")
    log = ROOT / "install.log"
    if log.exists():
        out(f"導入ログ: {log}")
    slog = s.data_dir / "server.log"
    if slog.exists():
        out(f"サーバーログ: {slog}")
        if not running and not after_install:
            out("--- server.log 末尾 ---")
            out(_tail(slog))

    out("")
    if after_install:
        out("導入は完了しました。この後ブラウザが開き、初回は API キーと書籍フォルダを設定する画面が出ます。")
        out("ブラウザが開かない場合は、次を開いてください: " + url)
        return 0
    if problems:
        out("要対応:")
        for p in problems:
            out(f"  - {p}")
        return 1
    out("問題は見つかりませんでした。" + ("" if running else " 起動するには start.bat（デスクトップの Legal-Agent）をダブルクリックしてください。"))
    return 0
