"""Tests for PDD failure log mirror field resolution."""

from __future__ import annotations

from pdd_agent.integrations.feishu.pdd_failure_log_read import _resolve_mirror_field_name


def test_resolve_mirror_field_name_exact_match():
    fields = [{"field_name": "处理状态镜像", "type": 1}]
    assert _resolve_mirror_field_name("处理状态镜像", fields) == "处理状态镜像"


def test_resolve_mirror_field_name_fuzzy_match():
    fields = [{"field_name": "（不要动）处理状态镜像", "type": 1}]
    assert _resolve_mirror_field_name("处理状态镜像", fields) == "（不要动）处理状态镜像"
