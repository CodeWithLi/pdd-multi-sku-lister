"""企业微信日报「正在解决 / 优化中」半自动草稿。"""

from __future__ import annotations

from datetime import datetime

from pdd_agent.api.services.pipeline_issue_report_service import ISSUE_TITLE_MAP, STAGE_LABELS
from pdd_agent.core.account_display import resolve_account_display_name
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import list_pipeline_issue_reports_between
from pdd_agent.db.session import is_database_available

logger = get_logger(__name__)

_MAX_AUTO_LINES = 5
_AUTO_SEVERITIES = ("error", "critical")


def _normalize_line(text: str) -> str:
    return str(text or "").strip().casefold()


def merge_in_progress_lines(manual: str, auto_lines: list[str]) -> str:
    """合并手动填写与系统建议：手动优先，自动补充未重复项。"""
    manual_lines = [line.strip() for line in str(manual or "").splitlines() if line.strip()]
    if not manual_lines:
        return "\n".join(auto_lines)
    seen = {_normalize_line(line) for line in manual_lines}
    extras = [line for line in auto_lines if _normalize_line(line) not in seen]
    return "\n".join(manual_lines + extras)


def _issue_display_title(row) -> str:
    title = str(row.title or "").strip()
    if title:
        return title
    reason = str(row.reason_code or "").strip()
    if reason:
        return ISSUE_TITLE_MAP.get(reason, reason)
    message = str(row.message or "").strip()
    if message:
        return message[:60]
    return "未分类问题"


def _format_issue_line(row) -> str:
    stage = str(row.stage or "").strip()
    stage_label = STAGE_LABELS.get(stage, stage or "链路")
    shop = resolve_account_display_name(str(row.account_id or "").strip()) or str(
        row.account_id or ""
    ).strip()
    title = _issue_display_title(row)
    selector = str(row.product_selector or "").strip()
    parts = [f"{stage_label}：{title}"]
    if shop:
        parts.append(f"（{shop}）")
    if selector:
        parts.append(f" · {selector}")
    return "".join(parts)


def collect_in_progress_draft_lines(
    *,
    window_start: datetime,
    window_end: datetime,
    limit: int = _MAX_AUTO_LINES,
) -> list[str]:
    """从整合链路报错记录生成「正在解决/优化中」建议条目。"""
    if not is_database_available():
        return []
    try:
        rows = list_pipeline_issue_reports_between(
            start=window_start,
            end=window_end,
            inclusive_end=True,
            severities=list(_AUTO_SEVERITIES),
            limit=max(limit * 3, 15),
        )
    except Exception:
        logger.exception("collect in progress draft failed")
        return []

    lines: list[str] = []
    seen: set[str] = set()
    for row in rows:
        line = _format_issue_line(row)
        key = _normalize_line(line)
        if not key or key in seen:
            continue
        seen.add(key)
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def resolve_pdd_in_progress(
    *,
    manual: str,
    window_start: datetime,
    window_end: datetime,
) -> tuple[str, list[str]]:
    """返回合并后的正文与系统建议草稿。"""
    auto_lines = collect_in_progress_draft_lines(
        window_start=window_start,
        window_end=window_end,
    )
    merged = merge_in_progress_lines(manual, auto_lines)
    return merged, auto_lines
