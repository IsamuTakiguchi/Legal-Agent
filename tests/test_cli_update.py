"""`python -m legal_agent update` の終了コード: 10 = 更新を適用、2 = 確認失敗、0 = 最新。start.ps1 が判定に使う。"""
import pytest

from legal_agent import __main__ as cli
from legal_agent import updater
from legal_agent.updater import UpdateStatus


def _run(monkeypatch, settings, status: UpdateStatus, argv=("update",)) -> int:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(updater, "check_and_update", lambda repo, branch, apply=True: status)
    try:
        cli.main(list(argv))
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def test_update_exit_codes(monkeypatch, settings):
    assert _run(monkeypatch, settings, UpdateStatus(applied=True, message="更新しました")) == 10
    assert _run(monkeypatch, settings, UpdateStatus(error="offline")) == 2
    assert _run(monkeypatch, settings, UpdateStatus(message="最新版です")) == 0
    assert _run(monkeypatch, settings, UpdateStatus(available=True, latest="abcdef0"), ("update", "--check")) == 0


def test_update_disabled(monkeypatch, settings):
    settings.auto_update = False
    called = []
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(updater, "check_and_update", lambda *a, **k: called.append(1) or UpdateStatus())
    cli.main(["update"])
    assert called == []
    with pytest.raises(SystemExit) as e:
        monkeypatch.setattr(updater, "check_and_update", lambda *a, **k: UpdateStatus(applied=True))
        cli.main(["update", "--force"])
    assert e.value.code == 10
