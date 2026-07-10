"""企业微信日报：店铺发布进度桥接（统计采集 + 格式化）。"""

from __future__ import annotations

from datetime import date, datetime

from pdd_agent.api.services.daily_shop_commerce_breakdown_stats import (
    rows_to_count_map,
    summarize_activity_618_success_between,
    summarize_activity_discount_success_between,
    summarize_promotion_success_for_report,
)
from pdd_agent.api.services.daily_shop_published_product_report_stats import (
    summarize_published_product_report_between,
)
from pdd_agent.core.report_time_window import report_listing_window
from pdd_agent.integrations.wecom.config import WecomConfig, load_wecom_config
from pdd_agent.integrations.wecom.daily_shop_publish_progress_report import (
    ShopPublishReportFormatOptions,
    ShopPublishReportStat,
    format_shop_publish_report_lines,
)


def _build_report_options(cfg: WecomConfig | None = None) -> ShopPublishReportFormatOptions:
    config = cfg or load_wecom_config()
    return ShopPublishReportFormatOptions(
        include_activity_promotion=bool(config.daily_report_include_activity_promotion),
        include_limited_time_gap=bool(config.daily_report_include_limited_time_gap),
    )


def _to_report_stat(
    item,
    *,
    activity_618_success_count: int = 0,
    activity_discount_success_count: int = 0,
    promotion_success_count: int = 0,
    include_limited_time_gap: bool = True,
) -> ShopPublishReportStat:
    return ShopPublishReportStat(
        account_id=item.account_id,
        shop_display_name=item.shop_display_name,
        published_count=item.published_count,
        limited_time_success_count=item.limited_time_success_count,
        activity_register_success_count=0,
        promotion_success_count=promotion_success_count,
        activity_618_success_count=activity_618_success_count,
        activity_discount_success_count=activity_discount_success_count,
        limited_time_failed_count=int(item.limited_time_failed_count or 0) if include_limited_time_gap else 0,
        limited_time_not_run_count=int(item.limited_time_not_run_count or 0) if include_limited_time_gap else 0,
        limited_time_failure_reasons=list(item.limited_time_failure_reasons or []) if include_limited_time_gap else [],
    )


def collect_shop_publish_report_stats(
    *,
    reference_day: date | None = None,
    now: datetime | None = None,
    config: WecomConfig | None = None,
) -> list[ShopPublishReportStat]:
    """采集日报窗口内店铺进度（以 published_products 为准）。"""
    cfg = config or load_wecom_config()
    options = _build_report_options(cfg)
    start, end = report_listing_window(reference_day=reference_day, now=now)
    published_stats = summarize_published_product_report_between(
        start=start,
        end=end,
        inclusive_end=True,
    )

    activity_618_by_account: dict[str, int] = {}
    activity_discount_by_account: dict[str, int] = {}
    promotion_by_account: dict[str, int] = {}
    if options.include_activity_promotion:
        activity_618_by_account = rows_to_count_map(
            summarize_activity_618_success_between(
                start=start,
                end=end,
                inclusive_end=True,
            )
        )
        activity_discount_by_account = rows_to_count_map(
            summarize_activity_discount_success_between(
                start=start,
                end=end,
                inclusive_end=True,
            )
        )
        promotion_by_account = rows_to_count_map(
            summarize_promotion_success_for_report(
                start=start,
                end=end,
                inclusive_end=True,
            )
        )

    report_stats: list[ShopPublishReportStat] = []
    seen_accounts: set[str] = set()
    for item in published_stats:
        account_id = str(item.account_id or "").strip()
        seen_accounts.add(account_id)
        report_stats.append(
            _to_report_stat(
                item,
                activity_618_success_count=activity_618_by_account.get(account_id, 0),
                activity_discount_success_count=activity_discount_by_account.get(account_id, 0),
                promotion_success_count=promotion_by_account.get(account_id, 0),
                include_limited_time_gap=options.include_limited_time_gap,
            )
        )

    if options.include_activity_promotion:
        for account_id, count in promotion_by_account.items():
            if account_id in seen_accounts or count <= 0:
                continue
            report_stats.append(
                ShopPublishReportStat(
                    account_id=account_id,
                    shop_display_name=account_id,
                    published_count=0,
                    promotion_success_count=count,
                )
            )

    report_stats.sort(
        key=lambda item: (
            item.published_count,
            item.limited_time_success_count,
            item.activity_618_success_count,
            item.activity_discount_success_count,
            item.promotion_success_count,
        ),
        reverse=True,
    )
    return report_stats


def build_shop_publish_report_text(
    stats: list[ShopPublishReportStat],
    *,
    config: WecomConfig | None = None,
) -> str:
    options = _build_report_options(config)
    return format_shop_publish_report_lines(stats, options=options)


def collect_shop_publish_report_text(
    *,
    reference_day: date | None = None,
    now: datetime | None = None,
    config: WecomConfig | None = None,
) -> str:
    stats = collect_shop_publish_report_stats(
        reference_day=reference_day,
        now=now,
        config=config,
    )
    return build_shop_publish_report_text(stats, config=config)
