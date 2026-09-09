"""自動更新。GitHub 上の最新版を確認し、差分があれば入れ替える。

- git clone された環境: `git pull --ff-only`（ローカル変更があれば何もしない）
- ZIP で展開された環境: GitHub の archive ZIP を取得し、アプリのファイルだけ上書き（.env / data / .venv は保持）
更新後に pyproject.toml が変わっていれば依存関係を再インストールする。
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / ".update.json"
PRESERVE = {".env", "data", ".venv", ".git", "__pycache__", ".update.json", ".pytest_cache"}
API = "https://api.github.com"
UA = "LegalAgent-updater/0.1"


@dataclass
class UpdateStatus:
    mode: str = "zip"  # "git" | "zip" | "disabled"
    current: str = ""
    latest: str = ""
    available: bool = False
    applied: bool = False
    message: str = ""
    checked_at: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write_state(d: dict) -> None:
    STATE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _pyproject_hash(root: Path = ROOT) -> str:
    p = root / "pyproject.toml"
    return hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else ""


def is_git_checkout(root: Path = ROOT) -> bool:
    return (root / ".git").exists() and shutil.which("git") is not None


def _git(*args: str, root: Path = ROOT, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=timeout)


def current_commit(root: Path = ROOT) -> str:
    if is_git_checkout(root):
        r = _git("rev-parse", "HEAD", root=root)
        return r.stdout.strip() if r.returncode == 0 else ""
    return _read_state().get("commit", "")


def remote_commit(repo: str, branch: str, client: httpx.Client | None = None) -> tuple[str, str]:
    """(最新コミット SHA, 実際に使ったブランチ)。指定ブランチが無ければ既定ブランチにフォールバック。"""
    own = client is None
    client = client or httpx.Client(timeout=15, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    try:
        r = client.get(f"{API}/repos/{repo}/commits/{branch}")
        if r.status_code == 404 or r.status_code == 422:
            info = client.get(f"{API}/repos/{repo}")
            info.raise_for_status()
            branch = info.json().get("default_branch", "main")
            r = client.get(f"{API}/repos/{repo}/commits/{branch}")
        r.raise_for_status()
        return r.json()["sha"], branch
    finally:
        if own:
            client.close()


def _reinstall(root: Path = ROOT, out=print) -> None:
    out("依存関係を更新しています…")
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-e", str(root)], check=False)


def apply_zip(repo: str, sha: str, root: Path = ROOT, client: httpx.Client | None = None, out=print) -> int:
    """archive ZIP を取得してアプリのファイルを上書きする。戻り値: 書き込んだファイル数。"""
    own = client is None
    client = client or httpx.Client(timeout=120, headers={"User-Agent": UA}, follow_redirects=True)
    try:
        r = client.get(f"https://github.com/{repo}/archive/{sha}.zip")
        r.raise_for_status()
        data = r.content
    finally:
        if own:
            client.close()
    before = _pyproject_hash(root)
    written = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        prefix = names[0].split("/")[0] + "/" if names else ""
        for name in names:
            if not name.startswith(prefix) or name.endswith("/"):
                continue
            rel = Path(name[len(prefix):])
            if not rel.parts or rel.parts[0] in PRESERVE:
                continue
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            content = zf.read(name)
            if dest.exists() and dest.read_bytes() == content:
                continue
            dest.write_bytes(content)
            written += 1
    if _pyproject_hash(root) != before:
        _reinstall(root, out)
    return written


def check_and_update(repo: str, branch: str, apply: bool = True, root: Path = ROOT, out=print, client: httpx.Client | None = None) -> UpdateStatus:
    st = UpdateStatus(checked_at=time.time())
    try:
        if is_git_checkout(root):
            st.mode = "git"
            st.current = current_commit(root)
            fetch = _git("fetch", "--quiet", "origin", branch, root=root, timeout=120)
            if fetch.returncode != 0:
                raise RuntimeError(fetch.stderr.strip() or "git fetch に失敗")
            st.latest = _git("rev-parse", "FETCH_HEAD", root=root).stdout.strip()
            st.available = bool(st.latest) and st.latest != st.current
            if st.available and apply:
                if _git("status", "--porcelain", root=root).stdout.strip():
                    st.message = "ローカルに変更があるため自動更新を見送りました（git pull を手動で実行してください）"
                    return st
                before = _pyproject_hash(root)
                pull = _git("merge", "--ff-only", "FETCH_HEAD", root=root)
                if pull.returncode != 0:
                    raise RuntimeError(pull.stderr.strip() or "git merge に失敗")
                if _pyproject_hash(root) != before:
                    _reinstall(root, out)
                st.applied = True
                st.current = st.latest
                st.message = f"更新しました（{st.latest[:7]}）"
            return st
        st.mode = "zip"
        state = _read_state()
        st.current = state.get("commit", "")
        st.latest, used_branch = remote_commit(repo, branch, client)
        st.available = st.latest != st.current
        if st.available and apply:
            out(f"新しい版があります（{st.latest[:7]}）。更新しています…")
            n = apply_zip(repo, st.latest, root, client, out)
            _write_state({"repo": repo, "branch": used_branch, "commit": st.latest, "updated_at": time.time()})
            st.applied = True
            st.current = st.latest
            st.message = f"更新しました（{n} ファイル、{st.latest[:7]}）"
        elif not st.available:
            st.message = "最新版です"
        return st
    except Exception as e:  # noqa: BLE001
        st.error = f"{type(e).__name__}: {e}"
        log.warning("自動更新の確認に失敗: %s", st.error)
        return st
