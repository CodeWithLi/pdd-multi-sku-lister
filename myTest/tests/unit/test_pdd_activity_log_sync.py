"""PDD活动日志表单元测试。"""



from __future__ import annotations



from datetime import datetime



import pytest



from pdd_agent.integrations.feishu.config import FeishuConfig, PddActivityLogConfig

from pdd_agent.integrations.feishu.pdd_activity_log_sync import (

    load_activity_log_product_context,

    map_activity_register_activity_status,

    map_limited_time_activity_status,

    normalize_activity_register_failure_reason_option,

    push_pdd_activity_log_activity_register,

    push_pdd_activity_log_limited_time,

    push_pdd_activity_log_seed,

    resolve_activity_log_phase,

    safe_load_activity_log_product_context,

)





@pytest.fixture

def activity_cfg() -> FeishuConfig:

    return FeishuConfig(

        app_id="x",

        app_secret="y",

        bitable_app_token="z",

        pdd_activity_log=PddActivityLogConfig(enabled=True, table_id="tbl_activity"),

    )





def test_map_activity_status_values():
    assert map_limited_time_activity_status(success=True) == "成功"
    assert map_limited_time_activity_status(success=False) == "失败"
    assert map_limited_time_activity_status(success=False, error="cannot import name 'x'") == "程序异常"
    assert map_activity_register_activity_status(success=True) == "报名成功"
    assert map_activity_register_activity_status(success=False) == "失败"
    assert map_activity_register_activity_status(success=False, error="Traceback (most recent call last)") == "程序异常"


def test_normalize_activity_register_failure_reason_option():
    opts = ["新商品需等24h后才可报", "活动价格低于成本价", "程序异常"]
    assert (
        normalize_activity_register_failure_reason_option("商品需过24h后才可以报活动", opts)
        == "新商品需等24h后才可报"
    )
    assert normalize_activity_register_failure_reason_option("立减后低于成本", opts) == "活动价格低于成本价"
    assert normalize_activity_register_failure_reason_option("RecursionError: max depth", opts) == "程序异常"
    assert normalize_activity_register_failure_reason_option("", opts) == ""




def test_resolve_activity_log_phase():

    cfg = FeishuConfig(app_id="x", app_secret="y", bitable_app_token="z")

    assert resolve_activity_log_phase("20981", cfg) == "activity_618"

    assert resolve_activity_log_phase("21365", cfg) == "activity_discount"

    assert resolve_activity_log_phase("99999", cfg) == "unknown"





def test_load_activity_log_product_context(activity_cfg, monkeypatch):

    from pdd_agent.integrations.feishu import pdd_activity_log_sync



    monkeypatch.setattr(

        pdd_activity_log_sync,

        "_resolve_account_display_name",

        lambda account_id, config: "测试店",

    )

    ctx = load_activity_log_product_context("store_A", ["968277091707"], config=activity_cfg)

    assert ctx["968277091707"]["account_name"] == "测试店"





def test_push_pdd_activity_log_seed_creates_pending_row(monkeypatch, activity_cfg):

    from pdd_agent.integrations.feishu import pdd_activity_log_sync



    names = activity_cfg.pdd_activity_log.field_names

    def fake_resolve(**kwargs):
        return {
            "日期": 1,
            "店铺名称": "测试店",
            names.product_id: kwargs.get("product_id"),
            names.marketing_tool_name: "限时限量购",
            names.activity_plan: "商品原价立减5元",
            names.limited_time_status: "未执行",
            names.marketing_activity_618: "618",
            names.activity_618_status: "未执行",
            names.marketing_activity_discount: "7折",
            names.activity_discount_status: "未执行",
        }



    monkeypatch.setattr(pdd_activity_log_sync, "_resolve_activity_log_identity", fake_resolve)

    monkeypatch.setattr(

        pdd_activity_log_sync,

        "resolve_pdd_activity_log_table_id",

        lambda *a, **k: ("tbl_activity", "configured"),

    )

    monkeypatch.setattr(pdd_activity_log_sync, "ensure_fields", lambda *a, **k: None)

    monkeypatch.setattr(pdd_activity_log_sync, "_find_activity_log_record", lambda *a, **k: None)

    monkeypatch.setattr(pdd_activity_log_sync, "map_fields_to_table_names", lambda *a, **k: a[-1])

    monkeypatch.setattr(pdd_activity_log_sync, "batch_create_records", lambda *a, **k: ["rec_seed"])



    result = push_pdd_activity_log_seed(

        account_id="store_A",

        product_id="968277091707",

        account_name="测试店",

        seeded_at=datetime(2026, 6, 21, 12, 0, 0),

        config=activity_cfg,

    )

    assert result.get("created") is True

    assert result.get("record_id") == "rec_seed"





def test_push_pdd_activity_log_seed_skips_existing(monkeypatch, activity_cfg):

    from pdd_agent.integrations.feishu import pdd_activity_log_sync



    monkeypatch.setattr(

        pdd_activity_log_sync,

        "resolve_pdd_activity_log_table_id",

        lambda *a, **k: ("tbl_activity", "configured"),

    )

    monkeypatch.setattr(pdd_activity_log_sync, "ensure_fields", lambda *a, **k: None)

    monkeypatch.setattr(

        pdd_activity_log_sync,

        "_find_activity_log_record",

        lambda *a, **k: {"record_id": "rec_existing"},

    )



    result = push_pdd_activity_log_seed(

        account_id="store_A",

        product_id="968277091707",

        account_name="测试店",

        config=activity_cfg,

    )

    assert result.get("skipped") is True

    assert result.get("reason") == "already_seeded"





def test_push_pdd_activity_log_limited_time_creates_row(monkeypatch, activity_cfg):

    from pdd_agent.integrations.feishu import pdd_activity_log_sync



    captured: list[dict] = []



    def fake_upsert(**kwargs):

        captured.append(kwargs)

        return {"created": True, "record_id": "rec1"}



    monkeypatch.setattr(pdd_activity_log_sync, "upsert_pdd_activity_log_fields", fake_upsert)



    names = activity_cfg.pdd_activity_log.field_names

    push_pdd_activity_log_limited_time(
        account_id="store_A",
        product_ids=["968277091707"],
        success=True,
        account_name="测试店",
        config=activity_cfg,
    )
    assert captured[0]["product_id"] == "968277091707"
    assert captured[0]["account_name"] == "测试店"
    assert captured[0]["identity_mode"] == "immediate"
    assert captured[0]["patch_fields"][names.limited_time_status] == "成功"
    assert captured[0]["patch_fields"][names.limited_time_failure_reason] == ""
    assert names.marketing_tool_published_at in captured[0]["patch_fields"]


def test_push_pdd_activity_log_limited_time_partial_success_marks_failures(monkeypatch, activity_cfg):
    from pdd_agent.integrations.feishu import pdd_activity_log_sync

    captured: list[dict] = []

    def fake_upsert(**kwargs):
        captured.append(kwargs)
        return {"updated": True, "record_id": "rec1"}

    monkeypatch.setattr(pdd_activity_log_sync, "upsert_pdd_activity_log_fields", fake_upsert)

    names = activity_cfg.pdd_activity_log.field_names
    push_pdd_activity_log_limited_time(
        account_id="store_A",
        product_ids=["111", "222", "333"],
        success=True,
        product_errors={
            "222": "活动价格不符合价格区间，不继续创建活动",
            "333": "活动价格不符合价格区间，不继续创建活动",
        },
        account_name="测试店",
        config=activity_cfg,
    )

    by_pid = {row["product_id"]: row["patch_fields"] for row in captured}
    assert by_pid["111"][names.limited_time_status] == "成功"
    assert by_pid["111"][names.limited_time_failure_reason] == ""
    assert by_pid["222"][names.limited_time_status] == "失败"
    assert "价格区间" in by_pid["222"][names.limited_time_failure_reason]
    assert by_pid["333"][names.limited_time_status] == "失败"


def test_push_pdd_activity_log_limited_time_failure_writes_reason(monkeypatch, activity_cfg):
    from pdd_agent.integrations.feishu import pdd_activity_log_sync

    captured: list[dict] = []

    def fake_upsert(**kwargs):
        captured.append(kwargs)
        return {"updated": True, "record_id": "rec1"}

    monkeypatch.setattr(pdd_activity_log_sync, "upsert_pdd_activity_log_fields", fake_upsert)

    names = activity_cfg.pdd_activity_log.field_names

    push_pdd_activity_log_limited_time(
        account_id="store_A",
        product_ids=["968599179476"],
        success=False,
        error="cannot import name 'get_account_config'",
        account_name="多多跨境2601",
        config=activity_cfg,
    )

    assert captured[0]["patch_fields"][names.limited_time_status] == "程序异常"
    assert captured[0]["patch_fields"][names.limited_time_failure_reason] == "需人工查验"


def test_safe_load_activity_log_product_context_falls_back(monkeypatch, activity_cfg):
    from pdd_agent.integrations.feishu import pdd_activity_log_sync

    def boom(*args, **kwargs):
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(pdd_activity_log_sync, "load_activity_log_product_context", boom)

    ctx = safe_load_activity_log_product_context(
        "store_A",
        ["968599179476"],
        account_name="多多跨境2601",
        config=activity_cfg,
    )
    assert ctx["968599179476"]["account_name"] == "多多跨境2601"


def test_schedule_pdd_activity_log_limited_time_failure_is_sync(monkeypatch, activity_cfg):
    from pdd_agent.integrations.feishu import pdd_activity_log_sync

    calls: list[dict] = []

    def fake_safe(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(pdd_activity_log_sync, "load_feishu_config", lambda: activity_cfg)
    monkeypatch.setattr(pdd_activity_log_sync, "_push_pdd_activity_log_safe", fake_safe)

    pdd_activity_log_sync.schedule_pdd_activity_log_limited_time(
        account_id="store_A",
        product_ids=["968599179476"],
        success=False,
        error="browser timeout",
    )

    assert len(calls) == 1
    assert calls[0]["push_fn"] is pdd_activity_log_sync.push_pdd_activity_log_limited_time





def test_push_pdd_activity_log_activity_register_618_and_discount(monkeypatch, activity_cfg):

    from pdd_agent.integrations.feishu import pdd_activity_log_sync



    captured: list[dict] = []



    def fake_upsert(**kwargs):

        captured.append(kwargs)

        return {"updated": True}



    monkeypatch.setattr(pdd_activity_log_sync, "upsert_pdd_activity_log_fields", fake_upsert)



    names = activity_cfg.pdd_activity_log.field_names

    push_pdd_activity_log_activity_register(
        account_id="store_A",
        activity_id="20981",
        product_ids=["968277091707"],
        success=True,
        account_name="测试店",
        config=activity_cfg,
    )
    assert captured[-1]["identity_mode"] == "delayed"
    assert captured[-1]["patch_fields"][names.activity_618_status] == "报名成功"
    assert names.activity_618_published_at in captured[-1]["patch_fields"]

    push_pdd_activity_log_activity_register(
        account_id="store_A",
        activity_id="21365",
        product_ids=["968277091707"],
        success=False,
        error="拼多多未确认报名成功",
        account_name="测试店",
        config=activity_cfg,
    )
    assert captured[-1]["patch_fields"][names.activity_discount_status] == "失败"
    assert names.activity_discount_published_at in captured[-1]["patch_fields"]


def test_upsert_pdd_activity_log_fields_skips_unchanged(monkeypatch, activity_cfg):
    from pdd_agent.integrations.feishu import pdd_activity_log_sync

    names = activity_cfg.pdd_activity_log.field_names
    monkeypatch.setattr(
        pdd_activity_log_sync,
        "resolve_pdd_activity_log_table_id",
        lambda *a, **k: ("tbl_test", "table_name"),
    )
    monkeypatch.setattr(pdd_activity_log_sync, "ensure_fields", lambda *a, **k: None)
    monkeypatch.setattr(
        pdd_activity_log_sync,
        "map_fields_to_table_names",
        lambda *a, **k: {
            names.limited_time_status: "失败",
            names.limited_time_failure_reason: "活动价格不符合价格区间，不继续创建活动",
        },
    )
    monkeypatch.setattr(
        pdd_activity_log_sync,
        "_find_activity_log_record",
        lambda *a, **k: {
            "record_id": "rec1",
            "fields": {
                names.limited_time_status: "失败",
                names.limited_time_failure_reason: "活动价格不符合价格区间，不继续创建活动",
            },
        },
    )

    batch_updates: list = []
    monkeypatch.setattr(
        pdd_activity_log_sync,
        "batch_update_records",
        lambda *a, **k: batch_updates.append(k),
    )

    result = pdd_activity_log_sync.upsert_pdd_activity_log_fields(
        product_id="968599179476",
        patch_fields={
            names.limited_time_status: "失败",
            names.limited_time_failure_reason: "活动价格不符合价格区间，不继续创建活动",
        },
        account_id="store_A",
        account_name="测试店",
        identity_mode="immediate",
        config=activity_cfg,
        client=object(),
    )

    assert result.get("skipped") is True
    assert result.get("reason") == "unchanged"
    assert batch_updates == []

