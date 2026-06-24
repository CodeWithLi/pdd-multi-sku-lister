"""失败日志循环上架 claim 模块测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.integrations.feishu.config import PddFailureCycleRelistWatchConfig
from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim import (
    get_cycle_relist_claim,
    release_cycle_relist_claim,
    try_claim_cycle_relist,
)


def _watch(**kwargs) -> PddFailureCycleRelistWatchConfig:
    return PddFailureCycleRelistWatchConfig(**kwargs)


def test_try_claim_success(monkeypatch):
    redis_store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, value, nx=False, ex=None):
            if nx and key in redis_store:
                return False
            redis_store[key] = value
            return True

        def get(self, key):
            return redis_store.get(key)

        def delete(self, key):
            redis_store.pop(key, None)
            return 1

    monkeypatch.setattr(
        "pdd_agent.integrations.redis.client.get_redis_client",
        lambda **kwargs: FakeRedis(),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim.resolve_failure_log_table",
        lambda cfg, client: ("tbl1", "失败表", "table_name"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim.list_fields",
        lambda client, app_token, table_id: [
            {"field_name": "是否已循环上架", "type": 3, "property": {"options": [{"name": "循环上架中"}]}},
        ],
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim.map_fields_to_table_names",
        lambda client, app_token, table_id, fields: fields,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim.batch_update_records",
        lambda client, app_token, table_id, records: [records[0]["record_id"]],
    )

    cfg = MagicMock()
    cfg.bitable_app_token = "app"
    cfg.pdd_upload_log.failure_field_names.cycle_relist = "是否已循环上架"
    cfg.pdd_upload_log.failure_cycle_relist_watch = _watch()

    result = try_claim_cycle_relist(
        "recABC123",
        merchant_code="BD684A",
        config=cfg,
        client=MagicMock(),
    )
    assert result.ok is True
    assert result.claimed is True
    assert result.redis_claimed is True
    assert result.feishu_updated is True
    assert result.placeholder == "循环上架中"
    assert get_cycle_relist_claim("recABC123") is not None


def test_try_claim_redis_locked(monkeypatch):
    redis_store = {"pdd:failure_cycle_relist:claim:rec1": "{}"}

    class FakeRedis:
        def set(self, key, value, nx=False, ex=None):
            if nx and key in redis_store:
                return False
            redis_store[key] = value
            return True

        def get(self, key):
            return redis_store.get(key)

    monkeypatch.setattr(
        "pdd_agent.integrations.redis.client.get_redis_client",
        lambda **kwargs: FakeRedis(),
    )

    cfg = MagicMock()
    cfg.bitable_app_token = "app"
    cfg.pdd_upload_log.failure_cycle_relist_watch = _watch()

    result = try_claim_cycle_relist("rec1", config=cfg, client=MagicMock())
    assert result.ok is True
    assert result.claimed is False
    assert result.reason == "redis_locked"


def test_try_claim_rolls_back_redis_on_feishu_fail(monkeypatch):
    redis_store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, value, nx=False, ex=None):
            if nx and key in redis_store:
                return False
            redis_store[key] = value
            return True

        def get(self, key):
            return redis_store.get(key)

        def delete(self, key):
            redis_store.pop(key, None)
            return 1

    monkeypatch.setattr(
        "pdd_agent.integrations.redis.client.get_redis_client",
        lambda **kwargs: FakeRedis(),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim.resolve_failure_log_table",
        lambda cfg, client: ("tbl1", "失败表", "table_name"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim.list_fields",
        lambda client, app_token, table_id: [
            {"field_name": "是否已循环上架", "type": 3, "property": {"options": [{"name": "循环上架中"}]}},
        ],
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim.map_fields_to_table_names",
        lambda client, app_token, table_id, fields: fields,
    )
    def fake_batch_update(*args, **kwargs):
        from pdd_agent.integrations.feishu.client import FeishuAPIError

        raise FeishuAPIError("飞书 API 错误: invalid option")

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim.batch_update_records",
        fake_batch_update,
    )

    cfg = MagicMock()
    cfg.bitable_app_token = "app"
    cfg.pdd_upload_log.failure_field_names.cycle_relist = "是否已循环上架"
    cfg.pdd_upload_log.failure_cycle_relist_watch = _watch()

    result = try_claim_cycle_relist("recRollback", config=cfg, client=MagicMock())
    assert result.ok is False
    assert result.claimed is False
    assert get_cycle_relist_claim("recRollback") is None


def test_release_claim(monkeypatch):
    deleted: list[str] = []

    class FakeRedis:
        def delete(self, key):
            deleted.append(key)
            return 1

    monkeypatch.setattr(
        "pdd_agent.integrations.redis.client.get_redis_client",
        lambda **kwargs: FakeRedis(),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim.resolve_failure_log_table",
        lambda cfg, client: ("tbl1", "失败表", "table_name"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim.list_fields",
        lambda client, app_token, table_id: [
            {"field_name": "是否已循环上架", "type": 3, "property": {"options": [{"name": "已完成"}]}},
        ],
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim.map_fields_to_table_names",
        lambda client, app_token, table_id, fields: fields,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim.batch_update_records",
        lambda client, app_token, table_id, records: [records[0]["record_id"]],
    )

    cfg = MagicMock()
    cfg.bitable_app_token = "app"
    cfg.pdd_upload_log.failure_field_names.cycle_relist = "是否已循环上架"
    cfg.pdd_upload_log.failure_cycle_relist_watch = _watch(claim_completed_value="已完成")

    result = release_cycle_relist_claim("recRelease", config=cfg, client=MagicMock())
    assert result.ok is True
    assert result.reason == "released"
    assert result.placeholder == "已完成"
    assert deleted
