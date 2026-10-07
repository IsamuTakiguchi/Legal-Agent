""".env の自動移行: 旧既定モデルの行だけを新しい既定値に書き換え、ほかは 1 バイトも変えない。"""
from legal_agent.config import Settings
from legal_agent.env_migrate import migrate_env

NEW = Settings.model_fields["model"].default


def test_migrates_only_retired_default(tmp_path):
    env = tmp_path / ".env"
    original = (
        "# Legal-Agent 設定（セットアップで生成。手で編集してもよい）\r\n"
        "ANTHROPIC_API_KEY=sk-ant-dummy-key\r\n"
        "LEGAL_AGENT_PDF_DIRS=C:\\Users\\x\\OneDrive\\書籍\r\n"
        "LEGAL_AGENT_MODEL=claude-opus-5\r\n"
        "LEGAL_AGENT_EFFORT=high\r\n"
        "# LEGAL_AGENT_MODEL=claude-opus-5\r\n"
    )
    env.write_bytes(original.encode("utf-8"))
    changes = migrate_env(env)
    assert changes == [f"LEGAL_AGENT_MODEL: claude-opus-5 → {NEW}"]
    after = env.read_bytes().decode("utf-8")
    # 変わったのはモデルの 1 行だけ（API キー・コメント・CRLF はそのまま。コメント行の旧値も触らない）
    assert after == original.replace("LEGAL_AGENT_MODEL=claude-opus-5\r\n", f"LEGAL_AGENT_MODEL={NEW}\r\n", 1)
    assert after.count("\r\n") == original.count("\r\n")
    # 2 回目は何もしない
    assert migrate_env(env) == []
    assert env.read_bytes().decode("utf-8") == after
    assert not (tmp_path / ".env.tmp").exists()


def test_keeps_user_choice_and_autoconf(tmp_path):
    env = tmp_path / ".env"
    env.write_text("LEGAL_AGENT_MODEL=claude-sonnet-5\nLEGAL_AGENT_AUTOCONF_MODEL=claude-opus-5\n", encoding="utf-8")
    assert migrate_env(env) == [f"LEGAL_AGENT_AUTOCONF_MODEL: claude-opus-5 → {Settings.model_fields['autoconf_model'].default}"]
    text = env.read_text(encoding="utf-8")
    assert "LEGAL_AGENT_MODEL=claude-sonnet-5\n" in text  # 利用者が選んだモデルは変えない


def test_bom_and_missing_file(tmp_path):
    env = tmp_path / ".env"
    assert migrate_env(env) == []  # 無ければ何もしない
    env.write_bytes(b"\xef\xbb\xbfLEGAL_AGENT_MODEL = claude-opus-5\n")
    assert len(migrate_env(env)) == 1
    raw = env.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and raw.endswith(f"={NEW}\n".encode())
    s = Settings(_env_file=str(env))
    assert s.model == NEW


def test_retired_defaults_are_not_current():
    from legal_agent.env_migrate import RETIRED_DEFAULTS

    assert NEW not in RETIRED_DEFAULTS and Settings.model_fields["autoconf_model"].default not in RETIRED_DEFAULTS
