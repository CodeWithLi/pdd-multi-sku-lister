"""Tests for PDD failure log mirror field resolution."""

from __future__ import annotations

from pdd_agent.integrations.feishu.pdd_failure_log_read import (
    _resolve_mirror_field_name,
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
