"""循环上架候选：分页 search 拉取测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.integrations.feishu.bitable import iter_search_record_pages
from pdd_agent.integrations.feishu.config import PddFailureCycleRelistWatchConfig
from pdd_agent.integrations.feishu.pdd_failure_log_read import FailureLogTableContext
from pdd_agent.integrations.feishu.pdd_failure_log_watch import (
    _collect_cycle_relist_rows_via_search,
    list_cycle_relist_candidates,
)


def _ctx() -> FailureLogTableContext:
    return FailureLogTableContext(
        app_token="app",
        table_id="tbl",
        table_name="失败表",
        resolve_method="table_name",
        mirror_field_name="处理状态镜像",
        cycle_relist_field_name="是否已循环上架",
        account_name_field="店铺名称",
        account_id_field="account_id",
        failure_reason_field="失败原因",
        names=MagicMock(
            date="日期",
            merchant_code="商品编码",
            report_platform="报错平台",
            processor="处理人",
            processed_at="处理时间",
            record_type="记录类型",
            failure_reason="失败原因",
            publish_start="发布开始",
            publish_end="发布结束",
            duration_seconds="耗时",
        ),
    )


def test_list_candidates_uses_search_pages_not_full_table():
    watch = PddFailureCycleRelistWatchConfig(
        completed_statuses=["已结束"],
        fetch_limit=2,
        fetch_page_size=50,
    )
    cfg = MagicMock()
    cfg.pdd_upload_log.failure_cycle_relist_watch = watch
    cfg.bitable_app_token = "app"

    record = {
        "record_id": "rec1",
        "fields": {
            "处理状态镜像": "已结束",
            "是否已循环上架": None,
            "商品编码": "BD046A",
            "失败原因": "定价为空",
            "报错平台": "拼多多",
            "店铺名称": "兔兔潮玩屋",
        },
    }

    with patch(
        "pdd_agent.integrations.feishu.pdd_failure_log_watch.resolve_failure_log_table_context",
        return_value=_ctx(),
    ):
        with patch(
            "pdd_agent.integrations.feishu.pdd_failure_log_watch.build_cycle_relist_candidate_search_filter",
            return_value={"conjunction": "and", "conditions": []},
        ) as build_filter:
            with patch(
                "pdd_agent.integrations.feishu.pdd_failure_log_watch.iter_search_record_pages",
                return_value=[[record]],
            ) as iter_pages:
                with patch(
                    "pdd_agent.integrations.feishu.pdd_failure_log_watch.FeishuClient",
                ):
                    result = list_cycle_relist_candidates(cfg, MagicMock(), watch=watch)

    build_filter.assert_called_once()
    assert build_filter.call_args.kwargs["completed_status"] == "已结束"
    iter_pages.assert_called_once()
    assert result["ok"] is True
    assert result["total"] == 1
    assert result["items"][0]["merchant_code"] == "BD046A"


def test_search_pages_sort_newest_first_and_stop_after_cutoff():
    watch = PddFailureCycleRelistWatchConfig(
        completed_statuses=["已结束"],
        fetch_after_date="2026-07-14",
        fetch_page_size=50,
    )
    requested_second_page = False

    def pages(*_args, **_kwargs):
        nonlocal requested_second_page
        yield [
            {"parsed": {"record_id": "recent", "date": "2026/07/17 00:00"}},
            {"parsed": {"record_id": "old", "date": "2026/07/03 00:00"}},
        ]
        requested_second_page = True
        yield [{"parsed": {"record_id": "older", "date": "2026/06/30 00:00"}}]

    with patch(
        "pdd_agent.integrations.feishu.pdd_failure_log_watch.build_cycle_relist_candidate_search_filter",
        return_value={"conjunction": "and", "conditions": []},
    ):
        with patch(
            "pdd_agent.integrations.feishu.pdd_failure_log_watch.iter_search_record_pages",
            side_effect=pages,
        ) as iter_pages:
            with patch(
                "pdd_agent.integrations.feishu.pdd_failure_log_watch.parse_failure_log_record",
                side_effect=lambda record, _ctx: record["parsed"],
            ):
                rows = _collect_cycle_relist_rows_via_search(
                    _ctx(),
                    MagicMock(),
                    watch=watch,
                    page_size=50,
                )

    assert rows == [{"record_id": "recent", "date": "2026/07/17 00:00"}]
    assert iter_pages.call_args.kwargs["sort"] == [{"field_name": "日期", "desc": True}]
    assert requested_second_page is False


def test_iter_search_record_pages_sends_sort_to_feishu():
    client = MagicMock()
    client.request.side_effect = [
        {
            "data": {
                "items": [{"record_id": "rec1"}],
                "has_more": True,
                "page_token": "next-page",
            },
        },
        {"data": {"items": [{"record_id": "rec2"}], "has_more": False}},
    ]
    sort = [{"field_name": "日期", "desc": True}]

    pages = list(
        iter_search_record_pages(
            client,
            "app",
            "tbl",
            filter_body={"conjunction": "and", "conditions": []},
            page_size=50,
            sort=sort,
        )
    )

    assert pages == [[{"record_id": "rec1"}], [{"record_id": "rec2"}]]
    first_call, second_call = client.request.call_args_list
    assert first_call.kwargs["params"] == {"page_size": 50}
    assert second_call.kwargs["params"] == {
        "page_size": 50,
        "page_token": "next-page",
    }
    assert first_call.kwargs["json"]["sort"] == sort
