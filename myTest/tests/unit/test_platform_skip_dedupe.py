"""平台跳过去重 Redis 缓存与飞书同步测试。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    PipelineIntegrationConfig,
    PddUploadLogConfig,
    PddUploadFailureLogFieldNames,
)
from pdd_agent.integrations.feishu.listing_feishu_platform_guard import PLATFORM_SKIP_REASON
from pdd_agent.integrations.feishu import platform_skip_dedupe_cache as cache_mod


def test_list_platform_skip_records_dedupes_by_platform_and_code_only(monkeypatch):
    import pdd_agent.integrations.feishu.pdd_failure_log_read as mod

    names = PddUploadFailureLogFieldNames()
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pipeline=PipelineIntegrationConfig(platform_skip_dedupe_fetch_limit=100),
        pdd_upload_log=PddUploadLogConfig(failure_field_names=names),
    )

    records = [
        {
            "fields": {
                names.merchant_code: "BD751A",
                names.report_platform: "拼多多",
                names.account_name: "兔兔潮玩屋",
                names.failure_reason: PLATFORM_SKIP_REASON,
            }
        },
        {
            "fields": {
                names.merchant_code: "BD751A",
                names.report_platform: "拼多多",
                names.account_name: "其它店铺",
                names.failure_reason: PLATFORM_SKIP_REASON,
            }
        },
        {
            "fields": {
                names.merchant_code: "BD751B",
                names.report_platform: "拼多多",
                names.failure_reason: "定价为空",
            }
        },
    ]

    class FakeClient:
        pass

    monkeypatch.setattr(mod, "_resolve_failure_log_table", lambda *_args, **_kwargs: ("tbl_fail", "x", "id"))
    monkeypatch.setattr(mod, "list_all_records", lambda *_args, **_kwargs: records)

    rows = mod.list_platform_skip_records(config=cfg, client=FakeClient())
    assert rows == [{"merchant_code": "BD751A", "report_platform": "拼多多"}]


def test_platform_skip_entry_key():
    key = cache_mod.platform_skip_entry_key(platform="拼多多", merchant_code="bd751a")
    assert key == "拼多多|BD751A"


def test_parse_legacy_three_part_key():
    platform, code = cache_mod.parse_platform_skip_entry_key("拼多多|兔兔潮玩屋|BD751A")
    assert platform == "拼多多"
    assert code == "BD751A"


def test_filter_selectors_skips_all_shops_for_same_code(monkeypatch):
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pipeline=PipelineIntegrationConfig(platform_skip_dedupe_enabled=True),
    )

    monkeypatch.setattr(cache_mod, "platform_skip_dedupe_enabled", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        cache_mod,
        "_load_entries_from_redis",
        lambda: {"拼多多|BD751A", "拼多多|BD751B"},
    )

    result = cache_mod.filter_selectors_by_platform_skip_dedupe(
        ["BD751/第一套图/BD751A", "BD751/第一套图/BD751B", "BD700/第一套图/BD700A"],
        config=cfg,
    )
    assert result["skipped_count"] == 2
    assert result["passed_selectors"] == ["BD700/第一套图/BD700A"]


def test_is_platform_skip_merchant_code_disabled(monkeypatch):
    cache_mod._local_entries.clear()
    monkeypatch.setattr(cache_mod, "_load_entries_from_redis", lambda: set())
    monkeypatch.setattr(cache_mod, "platform_skip_dedupe_enabled", lambda *_args, **_kwargs: False)
    assert cache_mod.is_platform_skip_merchant_code("BD751A") is False
    assert cache_mod.is_platform_skip_merchant_code("BD751A", require_enabled=False) is False


def test_remember_platform_skip_merchant_code_updates_local_and_redis(monkeypatch):
    cache_mod._local_entries.clear()
    store: set[str] = set()

    class FakeRedis:
        def sadd(self, _key, member):
            store.add(str(member))

        def smembers(self, _key):
            return set(store)

    monkeypatch.setattr(cache_mod, "get_redis_client", lambda: FakeRedis())
    monkeypatch.setattr(
        cache_mod,
        "load_redis_config",
        lambda: type("Cfg", (), {"key_prefix": "pdd"})(),
    )

    cache_mod.remember_platform_skip_merchant_code("bd751a")
    assert "拼多多|BD751A" in cache_mod._local_entries
    assert store == {"拼多多|BD751A"}
    assert cache_mod.is_platform_skip_merchant_code(
        "BD751A",
        require_enabled=False,
    )


def test_schedule_platform_skip_failure_log_dedupes_by_merchant_code(monkeypatch):
    from pdd_agent.integrations.feishu import pdd_upload_sync as sync_mod
    from pdd_agent.integrations.feishu.listing_feishu_platform_guard import PLATFORM_SKIP_REASON

    pushed: list[dict] = []

    def fake_push(**kwargs):
        pushed.append(kwargs)
        return {"created": True, "record_ids": ["rec1"], "table_id": "tbl"}

    monkeypatch.setattr(
        sync_mod,
        "load_feishu_config",
        lambda: type(
            "Cfg",
            (),
            {"pdd_upload_log": type("Log", (), {"failure_log_enabled": True})()},
        )(),
    )
    monkeypatch.setattr(sync_mod, "push_pdd_upload_failure_log", fake_push)
    monkeypatch.setattr(
        cache_mod,
        "is_platform_skip_merchant_code",
        lambda *args, **kwargs: kwargs.get("require_enabled") is False,
    )
    monkeypatch.setattr(cache_mod, "remember_platform_skip_merchant_code", lambda *args, **kwargs: None)

    sync_mod.schedule_pdd_upload_failure_log(
        account_id="store_A",
        merchant_code="BD751A",
        failure_reason=PLATFORM_SKIP_REASON,
        report_platform="拼多多",
    )
    assert pushed == []
