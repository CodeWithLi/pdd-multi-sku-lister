"""PDD营销-活动日志表 — 各活动步骤执行时间回写（限时限量购 / 618 / 七折）。

仅在对应活动实际跑过后写入时间戳；成功与失败均记录，未执行的活动不写。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pdd_agent.integrations.feishu.bitable import FIELD_DATETIME
from pdd_agent.integrations.feishu.config import FeishuConfig, load_feishu_config

ActivityExecutionPhase = Literal["limited_time", "activity_618", "activity_discount"]

_DATETIME_PROPERTY = {"date_formatter": "yyyy/MM/dd HH:mm", "auto_fill": False}


def _ms_timestamp(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def resolve_activity_execution_time_field_name(
    phase: ActivityExecutionPhase,
    config: FeishuConfig | None = None,
) -> str:
    """按活动阶段返回飞书「发布时间」列名。"""
    names = (config or load_feishu_config()).pdd_activity_log.field_names
    if phase == "limited_time":
        return names.marketing_tool_published_at
    if phase == "activity_618":
        return names.activity_618_published_at
    if phase == "activity_discount":
        return names.activity_discount_published_at
    raise ValueError(f"unknown activity execution phase: {phase}")


def field_defs_for_activity_execution_times(config: FeishuConfig) -> list[dict[str, Any]]:
    """ensure_fields 用：三个活动执行时间列定义。"""
    names = config.pdd_activity_log.field_names
    return [
        {
            "field_name": names.marketing_tool_published_at,
            "type": FIELD_DATETIME,
            "property": dict(_DATETIME_PROPERTY),
        },
        {
            "field_name": names.activity_618_published_at,
            "type": FIELD_DATETIME,
            "property": dict(_DATETIME_PROPERTY),
        },
        {
            "field_name": names.activity_discount_published_at,
            "type": FIELD_DATETIME,
            "property": dict(_DATETIME_PROPERTY),
        },
    ]


def build_activity_execution_time_patch(
    phase: ActivityExecutionPhase,
    *,
    executed_at: datetime | None = None,
    config: FeishuConfig | None = None,
) -> dict[str, int]:
    """构建单活动步骤的执行时间 patch（毫秒时间戳，供 upsert 合并）。"""
    when = executed_at or datetime.now()
    field_name = resolve_activity_execution_time_field_name(phase, config)
    return {field_name: _ms_timestamp(when)}


def merge_activity_execution_time_patch(
    patch_fields: dict[str, Any],
    phase: ActivityExecutionPhase,
    *,
    executed_at: datetime | None = None,
    config: FeishuConfig | None = None,
) -> dict[str, Any]:
    """将执行时间合并进已有 patch；活动实际跑过后调用。"""
    merged = dict(patch_fields)
    merged.update(
        build_activity_execution_time_patch(phase, executed_at=executed_at, config=config)
    )
    return merged
