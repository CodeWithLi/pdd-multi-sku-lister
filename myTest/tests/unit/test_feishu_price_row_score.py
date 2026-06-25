"""飞书定价行评分与重复编码合并测试。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.pdd_price_compare_sync import (
    _build_code_price_catalog_from_feishu_records,
    _row_price_fields_score,
)


def test_row_price_fields_score_prefers_pricing_over_control_range_only():
    incomplete = {
        "商品编码": "BD083A",
        "PDD控价下限价格": 7.91,
        "PDD控价上限价格": 9.40,
        "拼多多控价": 7.91,
    }
    complete = {
        "商品编码": "BD083A",
        "拼多多定价": 8.40,
        "PDD控价下限价格": 7.91,
        "PDD控价上限价格": 9.40,
        "拼多多控价": 7.91,
    }
    incomplete_score = _row_price_fields_score(
        incomplete,
        min_field="PDD控价下限价格",
        max_field="PDD控价上限价格",
        pricing_field="拼多多定价",
        control_field="拼多多控价",
    )
    complete_score = _row_price_fields_score(
        complete,
        min_field="PDD控价下限价格",
        max_field="PDD控价上限价格",
        pricing_field="拼多多定价",
        control_field="拼多多控价",
    )
    assert complete_score > incomplete_score


def test_build_code_price_catalog_keeps_price_when_later_incomplete_row_exists():
    catalog = _build_code_price_catalog_from_feishu_records(
        [
            {
                "fields": {
                    "商品编码": "BD083A",
                    "拼多多定价": 8.40,
                }
            },
            {
                "fields": {
                    "商品编码": "BD083A",
                    "PDD控价上限价格": 9.40,
                }
            },
        ],
        code_field="商品编码",
        price_field="拼多多定价",
    )
    assert catalog.prices["BD083A"] == 8.40
    assert "BD083A" not in catalog.incomplete_codes
