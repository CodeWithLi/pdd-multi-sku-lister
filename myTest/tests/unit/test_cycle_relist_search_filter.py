"""循环上架候选：飞书 search filter 构建测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.integrations.feishu.pdd_failure_log_read import (
    FailureLogTableContext,
    build_cycle_relist_candidate_search_filter,
    build_cycle_relist_empty_condition,
)


def _ctx() -> FailureLogTableContext:
    return FailureLogTableContext(
        app_token="app",
        table_id="tbl",
        table_name="失败表",
        resolve_method="table_name",
        mirror_field_name="（不要动）处理状态镜像",
        cycle_relist_field_name="是否已循环上架",
        account_name_field="店铺名称",
        account_id_field="account_id",
        failure_reason_field="失败原因",
        names=MagicMock(),
    )


def test_build_filter_single_status_and_cycle_relist_empty():
    api = MagicMock()
    with patch(
        "pdd_agent.integrations.feishu.pdd_failure_log_read.resolve_table_field_name",
        side_effect=lambda _c, _a, _t, name: name,
    ):
        with patch(
            "pdd_agent.integrations.feishu.bitable.get_table_field_meta",
            return_value={"是否已循环上架": {"type": 3, "ui_type": "SingleSelect"}},
        ):
            with patch(
                "pdd_agent.integrations.feishu.field_display.is_checkbox_like_cycle_relist_field",
                return_value=False,
            ):
                body = build_cycle_relist_candidate_search_filter(
                    _ctx(),
                    api,
                    completed_status="已结束",
                )
    assert body["conjunction"] == "and"
    assert "children" not in body
    assert body["conditions"] == [
        {
            "field_name": "（不要动）处理状态镜像",
            "operator": "is",
            "value": ["已结束"],
        },
    ]


def test_build_empty_condition_for_checkbox_field():
    api = MagicMock()
    with patch(
        "pdd_agent.integrations.feishu.pdd_failure_log_read.resolve_table_field_name",
        side_effect=lambda _c, _a, _t, name: name,
    ):
        with patch(
            "pdd_agent.integrations.feishu.bitable.get_table_field_meta",
            return_value={"是否已循环上架": {"type": 3, "ui_type": "Checkbox"}},
        ):
            with patch(
                "pdd_agent.integrations.feishu.field_display.is_checkbox_like_cycle_relist_field",
                return_value=True,
            ):
                cond = build_cycle_relist_empty_condition(api, _ctx())
    assert cond["operator"] == "is"
    assert cond["value"] == [False]
