"""Tests for PDD failure log mirror field resolution."""

from __future__ import annotations

from types import SimpleNamespace

from pdd_agent.integrations.feishu.pdd_failure_log_read import (
    FailureLogTableContext,
    _resolve_mirror_field_name,
    parse_failure_log_record,
    read_failure_log_account,
    resolve_failure_log_account_field_name,
)


def test_resolve_mirror_field_name_exact_match():
    fields = [{"field_name": "处理状态镜像", "type": 1}]
    assert _resolve_mirror_field_name("处理状态镜像", fields) == "处理状态镜像"


def test_resolve_mirror_field_name_fuzzy_match():
    fields = [{"field_name": "（不要动）处理状态镜像", "type": 1}]
    assert _resolve_mirror_field_name("处理状态镜像", fields) == "（不要动）处理状态镜像"


def test_resolve_failure_log_account_field_name_prefers_shop_alias():
    fields = [{"field_name": "店铺", "type": 1}]
    assert resolve_failure_log_account_field_name("店铺名称", fields) == "店铺"


def test_read_failure_log_account_from_shop_column():
    account_name, account_id = read_failure_log_account(
        {"店铺": "兔兔潮玩屋"},
        account_name_field="店铺",
    )
    assert account_name == "兔兔潮玩屋"
    assert account_id == ""


def test_parse_failure_log_merchant_code_from_rich_text():
    names = SimpleNamespace(
        date="日期",
        merchant_code="商品编码",
        report_platform="报错平台",
        record_type="记录类型",
        failure_reason="失败原因",
        publish_start="发布开始",
        publish_end="发布结束",
        duration_seconds="耗时秒",
        processor="人员",
        processed_at="处理时间",
        system_reason="系统原因",
    )
    ctx = FailureLogTableContext(
        app_token="app",
        table_id="tbl",
        table_name="失败表",
        resolve_method="table_name",
        mirror_field_name="处理状态镜像",
        cycle_relist_field_name="是否已循环上架",
        account_name_field="店铺",
        account_id_field="",
        failure_reason_field="失败原因",
        names=names,
    )

    item = parse_failure_log_record(
        {
            "record_id": "rec1",
            "fields": {
                "商品编码": [{"text": "BD070R", "type": "text"}],
                "处理状态镜像": "已结束",
            },
        },
        ctx,
    )

    assert item["merchant_code"] == "BD070R"
