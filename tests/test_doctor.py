"""doctor コマンドがインストール先・設定・索引・サーバー状態を表示すること。"""
from legal_agent import doctor


def test_doctor_reports(settings, monkeypatch, tmp_path):
    import legal_agent.config as cfg

    monkeypatch.setattr(cfg, "get_settings", lambda: settings)
    monkeypatch.setattr(cfg, "sdk_has_credentials", lambda: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out: list[str] = []
    code = doctor.run_doctor(after_install=False, out=out.append)
    text = "\n".join(out)
    assert "インストール先:" in text and "ライブラリ: インストール済み" in text
    assert "API キー: 未設定" in text and "索引: 0 冊" in text and "サーバー: 停止中" in text
    assert code == 0
    out.clear()
    assert doctor.run_doctor(after_install=True, out=out.append) == 0
    assert any("導入は完了しました" in line for line in out)


def test_doctor_appends_to_report_file(settings, monkeypatch, tmp_path):
    import legal_agent.config as cfg

    monkeypatch.setattr(cfg, "get_settings", lambda: settings)
    monkeypatch.setattr(cfg, "sdk_has_credentials", lambda: False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    report = tmp_path / "status.txt"
    report.write_text("Legal-Agent check started\r\nFolder: X\r\n", encoding="utf-8")
    doctor.run_doctor(after_install=False, out=lambda s: None, file=report)
    text = report.read_text(encoding="utf-8")
    assert text.startswith("Legal-Agent check started") and "インストール先:" in text
    # 新規ファイルなら BOM 付き
    fresh = tmp_path / "new.txt"
    doctor.run_doctor(after_install=False, out=lambda s: None, file=fresh)
    assert fresh.read_bytes().startswith(b"\xef\xbb\xbf")


def test_doctor_warns_when_inside_onedrive(settings, monkeypatch, tmp_path):
    import legal_agent.config as cfg

    monkeypatch.setattr(cfg, "get_settings", lambda: settings)
    monkeypatch.setattr(cfg, "sdk_has_credentials", lambda: False)
    monkeypatch.setattr(doctor, "ROOT", tmp_path / "OneDrive - Office" / "Legal-Agent")
    out: list[str] = []
    assert doctor.run_doctor(after_install=False, out=out.append) == 1
    assert any("OneDrive" in line for line in out)
