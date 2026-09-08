"""設定の読み込み。特に PDF_DIRS のカンマ区切り（Windows パス・日本語）が環境変数から読めること。"""
from pathlib import Path

from legal_agent.config import Settings


def test_pdf_dirs_from_env_comma_separated(monkeypatch, tmp_path):
    monkeypatch.setenv("LEGAL_AGENT_PDF_DIRS", r"C:\Users\me\OneDrive\書籍, D:\books ,")
    monkeypatch.setenv("LEGAL_AGENT_DATA_DIR", str(tmp_path))
    s = Settings(_env_file=None)
    assert s.pdf_dirs == [Path(r"C:\Users\me\OneDrive\書籍"), Path(r"D:\books")]


def test_pdf_dirs_empty_and_list(monkeypatch, tmp_path):
    monkeypatch.setenv("LEGAL_AGENT_PDF_DIRS", "")
    assert Settings(_env_file=None, data_dir=tmp_path).pdf_dirs == []
    monkeypatch.delenv("LEGAL_AGENT_PDF_DIRS")
    assert Settings(_env_file=None, data_dir=tmp_path, pdf_dirs=[tmp_path]).pdf_dirs == [tmp_path]


def test_env_file_roundtrip(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("LEGAL_AGENT_PDF_DIRS=/a/b,/c/d\nLEGAL_AGENT_TKC_ENABLED=false\n", encoding="utf-8")
    monkeypatch.delenv("LEGAL_AGENT_PDF_DIRS", raising=False)
    s = Settings(_env_file=env, data_dir=tmp_path)
    assert s.pdf_dirs == [Path("/a/b"), Path("/c/d")] and s.tkc_enabled is False
    assert s.credentials("tkc") == ("", "")
