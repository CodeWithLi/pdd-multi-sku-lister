"""企业微信日报：店铺发布进度格式化（含限时缺口 / 活动 / 推广）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from pdd_agent.api.services.daily_shop_limited_time_gap_stats import (
    LimitedTimeFailureReasonStat,
    ShopLimitedTimeGapStat,
)
from pdd_agent.api.services.daily_shop_publish_stats import ShopPublishStat


@dataclass
class ShopPublishReportStat(ShopPublishStat):
    activity_618_success_count: int = 0
    activity_discount_success_count: int = 0
    limited_time_failed_count: int = 0
    limited_time_not_run_count: int = 0
    limited_time_failure_reasons: list[LimitedTimeFailureReasonStat] = field(default_factory=list)


@dataclass(frozen=True)
class ShopPublishReportFormatOptions:
    include_activity_promotion: bool = False
    include_limited_time_gap: bool = True


def _format_failure_reasons(reasons: list[LimitedTimeFailureReasonStat]) -> str:
    parts: list[str] = []
    for item in reasons:
        reason = str(item.reason or "").strip()
        count = int(item.count or 0)
        if not reason or count <= 0:
            continue
        parts.append(f"{reason}（{count}个）")
    return "、".join(parts)


def format_shop_publish_report_line(
    stat: ShopPublishReportStat,
    *,
    options: ShopPublishReportFormatOptions | None = None,
) -> str:
    """格式店铺行；可附加限时失败/未跑与活动推广统计。"""
    opts = options or ShopPublishReportFormatOptions()
    name = stat.shop_display_name or stat.account_id
    segments = [f"已发布{int(stat.published_count or 0)}个"]
    if int(stat.limited_time_success_count or 0) > 0:
        segments.append(f"限时限量购{int(stat.limited_time_success_count)}个")
    if opts.include_activity_promotion:
        if int(stat.activity_618_success_count or 0) > 0:
            segments.append(f"618大促{int(stat.activity_618_success_count)}个")
        if int(stat.activity_discount_success_count or 0) > 0:
            segments.append(f"7折{int(stat.activity_discount_success_count)}个")
        if int(stat.promotion_success_count or 0) > 0:
            segments.append(f"推广{int(stat.promotion_success_count)}个")

    lines = [f"{name}：" + " + ".join(segments)]
    if not opts.include_limited_time_gap:
        return lines[0]

    failed_count = int(stat.limited_time_failed_count or 0)
    not_run_count = int(stat.limited_time_not_run_count or 0)
    if failed_count <= 0 and not_run_count <= 0:
        return lines[0]

    if failed_count > 0:
        reasons_text = _format_failure_reasons(stat.limited_time_failure_reasons)
        if reasons_text:
            lines.append(f"  {failed_count}个失败，失败原因是：{reasons_text}")
        else:
            lines.append(f"  {failed_count}个失败，失败原因是：限时限量购未成功")
    if not_run_count > 0:
        lines.append(f"  {not_run_count}个限时限量购未跑。")
    return "\n".join(lines)


def format_shop_publish_report_lines(
    stats: list[ShopPublishReportStat],
    *,
    options: ShopPublishReportFormatOptions | None = None,
) -> str:
    lines: list[str] = []
    for stat in stats:
        if not stat.has_progress:
            continue
        lines.append(format_shop_publish_report_line(stat, options=options))
    return "\n".join(lines)
