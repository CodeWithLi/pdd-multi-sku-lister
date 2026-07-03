"""pipeline_limited_time_first_spec_price_policy 单元测试。"""

from pdd_agent.api.services.pipeline_limited_time_first_spec_price_policy import (
    parse_first_spec_after_discount_price,
    resolve_retail_cost_by_product_code,
)
from pdd_agent.skills.campaign.price_rules import CampaignPriceRange


def test_parse_first_spec_after_discount_price_from_label():
    text = (
        "ID:600253553478\nKT猫-白色单包\n拼单价\n¥8.10\n立减\n5\n立减后价格\n¥3.10\n"
        "KT猫-白色+挂件\n拼单价\n¥9.10\n立减后价格\n¥4.10"
    )
    assert parse_first_spec_after_discount_price(text) == 3.10


def test_parse_first_spec_after_discount_price_from_first_spec_segment():
    text = "拼单价 ¥8.10 立减 5 ¥3.10 拼单价 ¥9.10 ¥4.10"
    assert parse_first_spec_after_discount_price(text) == 3.10


def test_resolve_retail_cost_by_product_code():
    target = {"product_code": "BD046A", "pdd_product_id": "600253553478"}
    rule, reason = resolve_retail_cost_by_product_code(
        target,
        price_ranges={"BD046A": CampaignPriceRange(code="BD046A", min_price=0, max_price=0, retail_cost=2.5)},
        catalog=type("Catalog", (), {"source": "feishu"})(),
    )
    assert reason == ""
    assert rule is not None
    assert rule["retail_cost"] == 2.5
    assert rule["matched_by"] == "product_code"


def test_resolve_retail_cost_missing_product_code():
    rule, reason = resolve_retail_cost_by_product_code(
        {"product_code": ""},
        price_ranges=[],
        catalog=type("Catalog", (), {"source": "feishu"})(),
    )
    assert rule is None
    assert reason == "missing_product_code"
