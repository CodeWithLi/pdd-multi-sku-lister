"""店铺删除与 yaml 回填测试。"""

from dy_agent.api.services import config_service
from dy_agent.core.config import AccountConfig, YamlSettings, load_yaml_settings, save_yaml_settings


def test_delete_account_removes_yaml_entry(monkeypatch):
    settings = YamlSettings()
    settings.accounts = [
        AccountConfig(account_id="store_A", enabled=True, phone="13800000000"),
    ]
    save_yaml_settings(settings)

    monkeypatch.setattr(config_service, "db_accounts_enabled", lambda: True)
    monkeypatch.setattr(config_service, "delete_account_config", lambda _id: True)

    config_service.delete_account("store_A")

    reloaded = load_yaml_settings()
    assert reloaded.accounts == []
