"""企业微信日报 Markdown 排版。"""

from __future__ import annotations

from typing import Literal

DailyReportPlatform = Literal["pdd", "taobao"]


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _bullet_block(text: str, *, empty_label: str = "暂无") -> str:
    lines = _split_lines(text)
    if not lines:
        return f"> <font color=\"comment\">{empty_label}</font>"
    return "\n".join(f"- {line}" for line in lines)


def _platform_title(platform: DailyReportPlatform) -> str:
    return "PDD" if platform == "pdd" else "淘宝"


def build_daily_report_markdown(
    *,
    platform: DailyReportPlatform,
    report_date: str,
    progress_summary: str = "",
    store_progress: str = "",
    netdisk_materials: str = "",
    in_progress: str = "",
    listing_window: str = "",
) -> str:
    """组装企业微信群机器人 Markdown 日报。"""
    label = _platform_title(platform)
    parts = [
        f"## 运营日报 · {label}",
        f"> 日期：<font color=\"info\">{report_date}</font>",
        "",
    ]

    if platform == "pdd":
        parts.extend(
            [
                "### 当日已完成交付技术项目进展",
                _bullet_block(progress_summary, empty_label="今日暂无代码提交"),
                "",
                "### 店铺今日发布商品进度",
            ]
        )
        if listing_window:
            parts.append(f"> 统计窗口：<font color=\"comment\">{listing_window}</font>")
        parts.append(_bullet_block(store_progress, empty_label="暂无发布记录"))
        parts.extend(
            [
                "",
                "### 正在解决 / 优化中",
                _bullet_block(in_progress, empty_label="暂无"),
            ]
        )
        return "\n".join(parts)

    parts.extend(
        [
            "### 网盘素材和上架累计数据",
            _bullet_block(netdisk_materials, empty_label="暂无"),
            "",
            "### 正在解决 / 优化中",
            _bullet_block(in_progress, empty_label="暂无"),
        ]
    )
    return "\n".join(parts)
