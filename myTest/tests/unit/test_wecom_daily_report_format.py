"""企业微信日报 Markdown 排版测试。"""

from __future__ import annotations

from pdd_agent.integrations.wecom.daily_report_format import build_daily_report_markdown


def test_build_pdd_daily_report_markdown():
    text = build_daily_report_markdown(
        platform="pdd",
        report_date="2026-07-06",
        progress_summary="修复上架超时\n优化日报推送",
        store_progress="咔咔琳琳时尚店：已发布8个",
        in_progress="处理图片上传",
        listing_window="07-05 18:01 ~ 07-06 17:00",
    )
    assert "## 运营日报 · PDD" in text
    assert "- 修复上架超时" in text
    assert "- 咔咔琳琳时尚店：已发布8个" in text
    assert "- 处理图片上传" in text
    assert "07-05 18:01 ~ 07-06 17:00" in text


def test_build_taobao_daily_report_markdown():
    text = build_daily_report_markdown(
        platform="taobao",
        report_date="2026-07-06",
        netdisk_materials="新增素材 20 个",
        in_progress="整理 SKU",
    )
    assert "## 运营日报 · 淘宝" in text
    assert "- 新增素材 20 个" in text
    assert "- 整理 SKU" in text
