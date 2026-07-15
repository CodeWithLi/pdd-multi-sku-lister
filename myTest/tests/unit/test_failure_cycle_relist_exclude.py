"""循环上架排除失败原因：多短语规范化与匹配。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.failure_cycle_relist_exclude import (
    failure_reason_matches_exclude_phrases,
    normalize_exclude_failure_reason_phrases,
)
from pdd_agent.integrations.feishu.config import PddFailureCycleRelistWatchConfig
from pdd_agent.integrations.feishu.pdd_failure_log_watch import is_cycle_relist_candidate


def test_normalize_accepts_legacy_string():
    assert normalize_exclude_failure_reason_phrases(
        "该商品不适用于此平台上架，自动跳过，无需处理"
    ) == ["该商品不适用于此平台上架，自动跳过，无需处理"]


def test_normalize_accepts_list_and_dedupes():
    assert normalize_exclude_failure_reason_phrases(
        ["无有效SKU", "平台不适用", "无有效SKU", "  "]
    ) == ["无有效SKU", "平台不适用"]


def test_normalize_accepts_newline_or_comma_text():
    assert normalize_exclude_failure_reason_phrases(
        "平台不适用\n无有效SKU,定价为空"
    ) == ["平台不适用", "无有效SKU", "定价为空"]


def test_match_any_phrase():
    phrases = ["平台不适用", "无有效SKU"]
    assert failure_reason_matches_exclude_phrases("BD001A无有效SKU，跳过", phrases)
    assert failure_reason_matches_exclude_phrases("该商品平台不适用", phrases)
    assert not failure_reason_matches_exclude_phrases("BD001A拼多多定价为空", phrases)
    assert not failure_reason_matches_exclude_phrases("任意原因", [])


def test_watch_config_accepts_legacy_string():
    cfg = PddFailureCycleRelistWatchConfig(
        exclude_failure_reason_contains="无有效SKU",
    )
    assert cfg.exclude_failure_reason_contains == ["无有效SKU"]


def test_watch_config_accepts_multiple_phrases():
    cfg = PddFailureCycleRelistWatchConfig(
        exclude_failure_reason_contains=["平台不适用", "无有效SKU"],
    )
    assert cfg.exclude_failure_reason_contains == ["平台不适用", "无有效SKU"]


def test_candidate_rejects_any_of_multiple_exclude_phrases():
    watch = PddFailureCycleRelistWatchConfig(
        exclude_failure_reason_contains=["平台不适用", "无有效SKU"],
    )
    assert not is_cycle_relist_candidate(
        process_status="已处理完成",
        cycle_relist="",
        failure_reason="BD043B无有效SKU",
        watch=watch,
    )
    assert not is_cycle_relist_candidate(
        process_status="已处理完成",
        cycle_relist="",
        failure_reason="该商品不适用于此平台上架，自动跳过，无需处理",
        watch=PddFailureCycleRelistWatchConfig(
            exclude_failure_reason_contains=["平台不适用", "该商品不适用于此平台上架"],
        ),
    )
    assert is_cycle_relist_candidate(
        process_status="已处理完成",
        cycle_relist="",
        failure_reason="BD684A拼多多定价为空",
        watch=watch,
    )
