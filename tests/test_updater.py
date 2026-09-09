"""自動更新: ZIP 方式（GitHub archive）と git 方式、既定ブランチへのフォールバック。"""
import io
import json
import subprocess
import zipfile
from pathlib import Path

import httpx
import pytest

from legal_agent import updater


def _zip_bytes(prefix: str, files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(prefix + "/", "")
        for name, data in files.items():
            zf.writestr(f"{prefix}/{name}", data)
    return buf.getvalue()


def _client(sha: str, files: dict[str, bytes], branch_404: bool = False):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        url = str(req.url)
        if url.endswith(f"/commits/{'main' if branch_404 else 'feature'}"):
            return httpx.Response(200, json={"sha": sha})
        if "/commits/" in url:
            return httpx.Response(404, json={"message": "Not Found"})
        if url.endswith("/repos/o/r"):
            return httpx.Response(200, json={"default_branch": "main"})
        if url.endswith(f"/archive/{sha}.zip"):
            return httpx.Response(200, content=_zip_bytes(f"r-{sha}", files))
        return httpx.Response(500)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


@pytest.fixture
def app_root(tmp_path, monkeypatch):
    root = tmp_path / "app"
    (root / "legal_agent").mkdir(parents=True)
    (root / "legal_agent" / "a.py").write_text("old", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "index.sqlite3").write_bytes(b"db")
    monkeypatch.setattr(updater, "ROOT", root)
    monkeypatch.setattr(updater, "STATE_FILE", root / ".update.json")
    reinstalls = []
    monkeypatch.setattr(updater, "_reinstall", lambda root, out=print: reinstalls.append(root))
    return root, reinstalls


def test_zip_update_preserves_user_data(app_root):
    root, reinstalls = app_root
    files = {"legal_agent/a.py": b"new", "legal_agent/b.py": b"added", "pyproject.toml": b"[project]\nname='x'\n", ".env": b"HACK=1", "data/x": b"no"}
    client, calls = _client("abc1234def", files)
    st = updater.check_and_update("o/r", "feature", apply=True, root=root, out=lambda s: None, client=client)
    assert st.mode == "zip" and st.applied and st.available and st.latest == "abc1234def" and not st.error
    assert (root / "legal_agent" / "a.py").read_text() == "new" and (root / "legal_agent" / "b.py").read_text() == "added"
    assert (root / ".env").read_text() == "SECRET=1\n" and (root / "data" / "index.sqlite3").read_bytes() == b"db"
    assert not (root / "data" / "x").exists()
    assert json.loads((root / ".update.json").read_text())["commit"] == "abc1234def"
    assert reinstalls == []  # pyproject 変化なし
    # 2 回目は最新
    st2 = updater.check_and_update("o/r", "feature", apply=True, root=root, out=lambda s: None, client=client)
    assert st2.available is False and st2.applied is False and st2.message == "最新版です"
    # 依存関係が変わったら再インストール
    client3, _ = _client("fff", {"pyproject.toml": b"[project]\nname='x'\ndependencies=['y']\n"})
    st3 = updater.check_and_update("o/r", "feature", apply=True, root=root, out=lambda s: None, client=client3)
    assert st3.applied and reinstalls == [root]


def test_zip_check_only_and_branch_fallback(app_root):
    root, _ = app_root
    client, calls = _client("999", {"legal_agent/a.py": b"new"}, branch_404=True)
    st = updater.check_and_update("o/r", "feature", apply=False, root=root, out=lambda s: None, client=client)
    assert st.available and not st.applied and (root / "legal_agent" / "a.py").read_text() == "old"
    assert any(u.endswith("/repos/o/r") for u in calls)  # 既定ブランチへフォールバック
    st = updater.check_and_update("o/r", "feature", apply=True, root=root, out=lambda s: None, client=client)
    assert st.applied and json.loads((root / ".update.json").read_text())["branch"] == "main"


def test_network_error_is_reported_not_raised(app_root):
    root, _ = app_root
    client = httpx.Client(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))))
    st = updater.check_and_update("o/r", "feature", apply=True, root=root, out=lambda s: None, client=client)
    assert st.error and "ConnectError" in st.error and not st.applied


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


def test_git_mode(tmp_path, monkeypatch):
    pytest.importorskip("shutil")
    origin = tmp_path / "origin.git"
    _git("init", "--bare", "-q", str(origin), cwd=tmp_path)
    work = tmp_path / "work"
    _git("clone", "-q", str(origin), str(work), cwd=tmp_path)
    env = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
    (work / "pyproject.toml").write_text("[project]\nname='x'\n")
    _git(*env, "add", ".", cwd=work)
    _git(*env, "commit", "-q", "-m", "init", cwd=work)
    _git("push", "-q", "-u", "origin", "HEAD:main", cwd=work)
    clone = tmp_path / "clone"
    _git("clone", "-q", "-b", "main", str(origin), str(clone), cwd=tmp_path)
    reinstalls = []
    monkeypatch.setattr(updater, "_reinstall", lambda root, out=print: reinstalls.append(root))
    st = updater.check_and_update("o/r", "main", apply=True, root=clone, out=lambda s: None)
    assert st.mode == "git" and not st.available and not st.error
    # origin に新しいコミット
    (work / "new.py").write_text("x")
    _git(*env, "add", ".", cwd=work)
    _git(*env, "commit", "-q", "-m", "second", cwd=work)
    _git("push", "-q", "origin", "HEAD:main", cwd=work)
    st = updater.check_and_update("o/r", "main", apply=True, root=clone, out=lambda s: None)
    assert st.available and st.applied and (clone / "new.py").exists() and reinstalls == []
    # ローカル変更があるときは見送る
    (work / "third.py").write_text("y")
    _git(*env, "add", ".", cwd=work)
    _git(*env, "commit", "-q", "-m", "third", cwd=work)
    _git("push", "-q", "origin", "HEAD:main", cwd=work)
    (clone / "pyproject.toml").write_text("local edit")
    st = updater.check_and_update("o/r", "main", apply=True, root=clone, out=lambda s: None)
    assert st.available and not st.applied and "ローカルに変更" in st.message
