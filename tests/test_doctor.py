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
