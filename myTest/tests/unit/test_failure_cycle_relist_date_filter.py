"""失败日志抓取时间（飞书「日期」）筛选单测。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.config import PddFailureCycleRelistWatchConfig
from pdd_agent.integrations.feishu.failure_cycle_relist_date_filter import (
    normalize_fetch_after_date,
    parse_failure_log_date,
    record_date_meets_fetch_after,
)
from pdd_agent.integrations.feishu.pdd_failure_log_watch import is_cycle_relist_candidate


def test_parse_slash_and_dash_dates():
    assert parse_failure_log_date("2026/07/13").isoformat() == "2026-07-13"
    assert parse_failure_log_date("2026-07-15").isoformat() == "2026-07-15"
    assert parse_failure_log_date("2026-07-15 12:00:00").isoformat() == "2026-07-15"


def test_normalize_fetch_after_date():
    assert normalize_fetch_after_date("2026/07/13") == "2026-07-13"
    assert normalize_fetch_after_date("") == ""
    assert normalize_fetch_after_date(None) == ""


def test_record_date_meets_fetch_after():
    assert record_date_meets_fetch_after(record_date="2026/07/15", fetch_after_date="2026-07-13")
    assert record_date_meets_fetch_after(record_date="2026/07/13", fetch_after_date="2026-07-13")
    assert not record_date_meets_fetch_after(record_date="2026/07/12", fetch_after_date="2026-07-13")
    assert record_date_meets_fetch_after(record_date="2026/07/01", fetch_after_date="")
    assert not record_date_meets_fetch_after(record_date="", fetch_after_date="2026-07-13")


def test_candidate_filtered_by_fetch_after_date():
    watch = PddFailureCycleRelistWatchConfig(fetch_after_date="2026-07-14")
    assert is_cycle_relist_candidate(
        process_status="已结束",
        cycle_relist="",
        failure_reason="定价为空",
        watch=watch,
        record_date="2026/07/15",
    )
    assert not is_cycle_relist_candidate(
        process_status="已结束",
        cycle_relist="",
        failure_reason="定价为空",
        watch=watch,
        record_date="2026/07/13",
    )
