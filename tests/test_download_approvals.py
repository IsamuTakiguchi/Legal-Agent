"""クラウドのみ PDF のダウンロード許可制: 未許可はスキップして pending に載せ、許可後に索引する。"""
from pathlib import Path

import pymupdf

from legal_agent.index import indexer
from legal_agent.index.approvals import DownloadApprovals
from legal_agent.index.db import IndexDB
from legal_agent.index.indexer import index_dirs, pending_downloads


def _pdf(path: Path, text: str) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


def test_pending_then_allowed(tmp_path, monkeypatch):
    books = tmp_path / "books"
    local = _pdf(books / "local.pdf", "hello local")
    cloud = _pdf(books / "sub" / "cloud.pdf", "hello cloud")
    monkeypatch.setattr(indexer, "is_cloud_only", lambda p, platform=None: Path(p).name == "cloud.pdf")
    db = IndexDB(tmp_path / "index.sqlite3")
    appr = DownloadApprovals(tmp_path / "approvals.json")

    st = index_dirs(db, [books], log=lambda s: None, approvals=appr)
    assert st["added"] == 1 and st["pending"] == 1
    assert st["pending_files"][0]["name"] == "cloud.pdf" and st["pending_files"][0]["folder"] == "sub"
    assert [f["name"] for f in pending_downloads([books], appr)] == ["cloud.pdf"]
    assert db.stats()["documents"] == 1

    # 許可 → 次の索引で取り込まれ、pending から消える
    assert appr.allow([str(cloud)]) == 1
    st = index_dirs(db, [books], log=lambda s: None, approvals=appr)
    assert st["added"] == 1 and st["pending"] == 0 and st["skipped"] == 1 and db.stats()["documents"] == 2
    assert pending_downloads([books], appr) == []

    # 許可は保存され、再読込しても残る（大文字小文字は区別しない）
    appr2 = DownloadApprovals(tmp_path / "approvals.json")
    assert appr2.is_allowed(str(cloud).upper()) and not appr2.is_allowed(local)
    appr2.revoke([cloud])
    assert not appr2.is_allowed(cloud)


def test_allow_all_and_auto_download(tmp_path, monkeypatch):
    books = tmp_path / "books"
    _pdf(books / "a.pdf", "a")
    monkeypatch.setattr(indexer, "is_cloud_only", lambda p, platform=None: True)
    db = IndexDB(tmp_path / "index.sqlite3")
    # approvals 無し・自動ダウンロード無し → 全部 pending
    assert index_dirs(db, [books], log=lambda s: None)["pending"] == 1
    # 設定で自動ダウンロード → 取り込む
    assert index_dirs(db, [books], log=lambda s: None, download_cloud=True)["added"] == 1
    # allow_all
    appr = DownloadApprovals(tmp_path / "approvals.json")
    appr.set_allow_all(True)
    assert DownloadApprovals(tmp_path / "approvals.json").allow_all is True
    assert pending_downloads([books], appr) == []
