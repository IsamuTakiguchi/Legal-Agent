import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path, monkeypatch):
    from legal_agent.config import Settings

    monkeypatch.setenv("LEGAL_AGENT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("LEGAL_AGENT_PDF_DIRS", raising=False)
    s = Settings(_env_file=None, data_dir=tmp_path / "data", headless=True, min_interval_sec=0)
    s.ensure_dirs()
    return s


@pytest.fixture
def anyio_backend():
    return "asyncio"
