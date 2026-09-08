import os
from pathlib import Path
from types import SimpleNamespace

from legal_agent.index.indexer import iter_pdfs
from legal_agent.onedrive import (
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS,
    describe_dir,
    detect_onedrive_roots,
    is_cloud_only,
    list_pdf_folders,
    strip_quotes,
)


def test_detect_roots_windows(tmp_path):
    consumer = tmp_path / "OneDrive - Personal"
    consumer.mkdir()
    profile = tmp_path / "profile"
    (profile / "OneDrive").mkdir(parents=True)
    env = {"OneDriveConsumer": str(consumer), "OneDrive": str(consumer), "USERPROFILE": str(profile)}
    roots = detect_onedrive_roots(env=env, home=tmp_path / "nohome", platform="win32")
    assert roots == [consumer, profile / "OneDrive"]  # 重複は除去、存在しないものは除外


def test_detect_roots_mac_and_linux(tmp_path):
    cloud = tmp_path / "Library" / "CloudStorage"
    (cloud / "OneDrive-Personal").mkdir(parents=True)
    (cloud / "Dropbox").mkdir()
    assert detect_onedrive_roots(env={}, home=tmp_path, platform="darwin") == [cloud / "OneDrive-Personal"]
    assert detect_onedrive_roots(env={}, home=tmp_path, platform="linux") == []
    (tmp_path / "OneDrive").mkdir()
    assert detect_onedrive_roots(env={}, home=tmp_path, platform="linux") == [tmp_path / "OneDrive"]


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.4")


def test_list_pdf_folders(tmp_path):
    root = tmp_path / "OneDrive"
    _touch(root / "書籍" / "労働法" / "a.pdf")
    _touch(root / "書籍" / "労働法" / "b.pdf")
    _touch(root / "書籍" / "民法" / "c.pdf")
    _touch(root / "書籍" / "~$temp.pdf")  # 一時ファイルは数えない
    _touch(root / "写真" / "x.jpg")
    _touch(root / "事件" / "2024" / "訴状.pdf")
    _touch(root / "deep" / "l2" / "l3" / "l4" / "far.pdf")
    folders = list_pdf_folders(root, max_depth=3)
    names = [(p.relative_to(root).as_posix(), n) for p, n in folders]
    assert names[0] == ("書籍", 3)
    assert ("書籍/労働法", 2) in names and ("書籍/民法", 1) in names
    assert ("事件/2024", 1) in names and ("事件", 1) not in names  # 子と同じ件数の親は省く
    assert not any("写真" in n for n, _ in names)
    assert not any(n.startswith("deep/l2/l3/l4") for n, _ in names)


def test_is_cloud_only(monkeypatch, tmp_path):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"x")
    assert is_cloud_only(f, platform="linux") is False
    monkeypatch.setattr(os, "stat", lambda p: SimpleNamespace(st_file_attributes=FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | 0x20))
    assert is_cloud_only(f, platform="win32") is True
    monkeypatch.setattr(os, "stat", lambda p: SimpleNamespace(st_file_attributes=0x20))
    assert is_cloud_only(f, platform="win32") is False


def test_describe_dir_and_iter_pdfs(tmp_path):
    root = tmp_path / "books"
    _touch(root / "a.pdf")
    _touch(root / "sub" / "b.PDF")
    _touch(root / "~$lock.pdf")
    info = describe_dir(root)
    assert info == {"path": str(root), "exists": True, "pdfs": 2, "cloud_only": 0}
    assert describe_dir(tmp_path / "missing")["exists"] is False
    assert sorted(p.name for p in iter_pdfs([root])) == ["a.pdf", "b.PDF"]


def test_strip_quotes():
    assert strip_quotes('  "C:\\Users\\me\\OneDrive\\書籍"  ') == "C:\\Users\\me\\OneDrive\\書籍"
    assert strip_quotes("'x'") == "x" and strip_quotes("plain") == "plain"
