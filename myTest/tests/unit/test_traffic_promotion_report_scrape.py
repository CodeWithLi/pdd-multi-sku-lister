"""投流昨日数据抓取解析单元测试。"""

from pdd_agent.skills.traffic.promotion_report_scrape import (
    _map_row_metrics,
    _parse_metrics_from_text,
    _parse_rows_with_headers,
)


def test_parse_rows_with_headers_maps_product_id_and_metrics():
    headers = [
        "推广",
        "分组",
        "推广添加时间",
        "推广状态",
        "成交花费(元)",
        "交易额(元)",
        "实际投产比",
        "总花费(元)",
    ]
    raw_rows = [
        {
            "product_id": "967084305452",
            "cells": [
                "粉色包 商品ID：967084305452",
                "默认",
                "2026/06/16",
                "推广中",
                "12.50",
                "88.00",
                "7.04",
                "12.50",
            ],
            "row_text": "粉色包 商品ID：967084305452 ...",
        }
    ]
    parsed = _parse_rows_with_headers(raw_rows, headers)
    assert len(parsed) == 1
    assert parsed[0]["product_id"] == "967084305452"
    assert parsed[0]["metrics"]["spend"] == "12.50"
    assert parsed[0]["metrics"]["amount"] == "88.00"
    assert parsed[0]["metrics"]["roi"] == "7.04"


def test_parse_rows_prefers_js_metrics():
    raw_rows = [
        {
            "product_id": "967084305452",
            "cells": ["推广列", "余额不足 去充值", "详情 数据 更多"],
            "metrics": {
                "spend": "0.00",
                "amount": "0.00",
                "roi": "0.00",
                "total_cost": "0.00",
            },
            "row_text": "商品 ID: 967084305452",
        }
    ]
    parsed = _parse_rows_with_headers(raw_rows, [])
    assert parsed[0]["metrics"]["spend"] == "0.00"
    assert parsed[0]["metrics"]["amount"] == "0.00"
    assert "余额不足" not in parsed[0]["metrics"].values()


def test_map_row_metrics_keeps_zero_values():
    metrics = _map_row_metrics(
        ["成交花费(元)", "交易额(元)", "净成交笔数"],
        ["0.00", "0.00", "0"],
    )
    assert metrics["spend"] == "0.00"
    assert metrics["amount"] == "0.00"
    assert metrics["net_orders"] == "0"


def test_parse_metrics_from_text_with_spaced_product_id():
    row_text = (
        "粉色星星波点可爱收纳包 商品 ID: 967064505452 默认 2026/06/16 余额不足 "
        "预算日限额: 不限 净目标投产比: 3.25 0.00 0.00 0.00 0.00 0.00 - 0 -"
    )
    metrics = _parse_metrics_from_text(row_text)
    assert metrics["spend"] == "0.00"
    assert metrics["amount"] == "0.00"
    assert metrics.get("total_cost") == "0.00"
    assert len(metrics) >= 4


def test_map_row_metrics_partial_headers():
    metrics = _map_row_metrics(
        ["净成交笔数", "每笔净成交花费(元)"],
        ["3", "4.17"],
    )
    assert metrics["net_orders"] == "3"
    assert metrics["cost_per_order"] == "4.17"
