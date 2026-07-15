"""Tests for failure log cycle relist candidate filter."""

from __future__ import annotations

from pdd_agent.integrations.feishu.config import PddFailureCycleRelistWatchConfig
from pdd_agent.integrations.feishu.pdd_failure_log_watch import is_cycle_relist_candidate


def _watch(**kwargs) -> PddFailureCycleRelistWatchConfig:
    return PddFailureCycleRelistWatchConfig(**kwargs)


def test_candidate_matches_completed_empty_cycle_relist():
    assert is_cycle_relist_candidate(
        process_status="已结束",
        cycle_relist="",
        failure_reason="BD684A拼多多定价为空",
        watch=_watch(),
    )


def test_candidate_rejects_processing_status():
    assert not is_cycle_relist_candidate(
        process_status="正在处理",
        cycle_relist="",
        failure_reason="BD684A拼多多定价为空",
        watch=_watch(),
    )


def test_candidate_rejects_when_cycle_relist_filled():
    assert not is_cycle_relist_candidate(
        process_status="已结束",
        cycle_relist="是",
        failure_reason="BD684A拼多多定价为空",
        watch=_watch(),
    )


def test_candidate_accepts_false_cycle_relist_string():
    assert is_cycle_relist_candidate(
        process_status="已结束",
        cycle_relist="False",
        failure_reason="BD684A拼多多定价为空",
        watch=_watch(),
    )


def test_candidate_rejects_excluded_failure_reason():
    assert not is_cycle_relist_candidate(
        process_status="已处理完成",
        cycle_relist="",
        failure_reason="BD043B无有效SKU",
        watch=_watch(exclude_failure_reason_contains="无有效SKU"),
    )


def test_candidate_rejects_any_of_multiple_excluded_failure_reasons():
    watch = _watch(exclude_failure_reason_contains=["平台不适用", "无有效SKU"])
    assert not is_cycle_relist_candidate(
        process_status="已处理完成",
        cycle_relist="",
        failure_reason="该商品平台不适用，跳过",
        watch=watch,
    )
    assert is_cycle_relist_candidate(
        process_status="已处理完成",
        cycle_relist="",
        failure_reason="BD684A拼多多定价为空",
        watch=watch,
    )
