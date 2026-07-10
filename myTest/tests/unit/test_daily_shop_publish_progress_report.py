"""企业微信日报店铺进度格式化单元测试。"""

from __future__ import annotations

from pdd_agent.api.services.daily_shop_limited_time_gap_stats import LimitedTimeFailureReasonStat
from pdd_agent.integrations.wecom.daily_shop_publish_progress_report import (
    ShopPublishReportFormatOptions,
    ShopPublishReportStat,
    format_shop_publish_report_line,
    format_shop_publish_report_lines,
)


def test_format_shop_publish_report_line_default():
    line = format_shop_publish_report_line(
        ShopPublishReportStat(
            account_id="store_A",
            shop_display_name="兔兔潮玩屋",
            published_count=16,
            limited_time_success_count=12,
        )
    )
    assert line == "兔兔潮玩屋：已发布16个 + 限时限量购12个"


def test_format_shop_publish_report_line_with_activity_promotion():
    line = format_shop_publish_report_line(
        ShopPublishReportStat(
            account_id="store_A",
            shop_display_name="兔兔潮玩屋",
            published_count=132,
            limited_time_success_count=94,
            activity_618_success_count=3,
            activity_discount_success_count=3,
            promotion_success_count=5,
        ),
        options=ShopPublishReportFormatOptions(include_activity_promotion=True),
    )
    assert line == (
        "兔兔潮玩屋：已发布132个 + 限时限量购94个 + 618大促3个 + 7折3个 + 推广5个"
    )


def test_format_shop_publish_report_line_with_limited_time_gap():
    line = format_shop_publish_report_line(
        ShopPublishReportStat(
            account_id="store_A",
            shop_display_name="兔兔潮玩屋",
            published_count=132,
            limited_time_success_count=94,
            limited_time_failed_count=12,
            limited_time_not_run_count=26,
            limited_time_failure_reasons=[
                LimitedTimeFailureReasonStat(reason="飞书数据缺失", count=8),
                LimitedTimeFailureReasonStat(reason="价格低于成本价", count=4),
            ],
        ),
        options=ShopPublishReportFormatOptions(include_limited_time_gap=True),
    )
    assert line == (
        "兔兔潮玩屋：已发布132个 + 限时限量购94个\n"
        "  12个失败，失败原因是：飞书数据缺失（8个）、价格低于成本价（4个）\n"
        "  26个限时限量购未跑。"
    )


def test_format_shop_publish_report_lines_skips_zero():
    text = format_shop_publish_report_lines(
        [
            ShopPublishReportStat(account_id="a", shop_display_name="A店", published_count=0),
            ShopPublishReportStat(account_id="b", shop_display_name="B店", published_count=3),
        ]
    )
    assert text == "B店：已发布3个"
