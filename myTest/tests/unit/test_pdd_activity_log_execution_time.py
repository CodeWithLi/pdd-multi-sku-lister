"""PDD活动日志执行时间回写单元测试。"""

from __future__ import annotations

from datetime import datetime

import pytest

from pdd_agent.integrations.feishu.config import FeishuConfig, PddActivityLogConfig
from pdd_agent.integrations.feishu.pdd_activity_log_execution_time import (
    build_activity_execution_time_patch,
    field_defs_for_activity_execution_times,
    merge_activity_execution_time_patch,
    resolve_activity_execution_time_field_name,
)


@pytest.fixture
def activity_cfg() -> FeishuConfig:
    return FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_activity_log=PddActivityLogConfig(enabled=True, table_id="tbl_activity"),
    )


def test_resolve_activity_execution_time_field_name(activity_cfg):
    names = activity_cfg.pdd_activity_log.field_names
    assert resolve_activity_execution_time_field_name("limited_time", activity_cfg) == names.marketing_tool_published_at
    assert resolve_activity_execution_time_field_name("activity_618", activity_cfg) == names.activity_618_published_at
    assert (
        resolve_activity_execution_time_field_name("activity_discount", activity_cfg)
        == names.activity_discount_published_at
    )


def test_build_activity_execution_time_patch(activity_cfg):
    names = activity_cfg.pdd_activity_log.field_names
    when = datetime(2026, 6, 27, 17, 8, 0)
    patch = build_activity_execution_time_patch("limited_time", executed_at=when, config=activity_cfg)
    assert list(patch.keys()) == [names.marketing_tool_published_at]
    assert patch[names.marketing_tool_published_at] == int(when.timestamp() * 1000)


def test_field_defs_for_activity_execution_times(activity_cfg):
    names = activity_cfg.pdd_activity_log.field_names
    defs = field_defs_for_activity_execution_times(activity_cfg)
    field_names = {item["field_name"] for item in defs}
    assert field_names == {
        names.marketing_tool_published_at,
        names.activity_618_published_at,
        names.activity_discount_published_at,
    }


def test_merge_activity_execution_time_patch_preserves_existing(activity_cfg):
    names = activity_cfg.pdd_activity_log.field_names
    when = datetime(2026, 7, 1, 10, 0, 0)
    merged = merge_activity_execution_time_patch(
        {names.limited_time_status: "成功"},
        "limited_time",
        executed_at=when,
        config=activity_cfg,
    )
    assert merged[names.limited_time_status] == "成功"
    assert names.marketing_tool_published_at in merged
