"""投流昨日数据抓取解析单元测试。"""

from pdd_agent.integrations.feishu.traffic_metric_columns import normalize_traffic_metrics
from pdd_agent.skills.traffic.promotion_report_scrape import (
    _parse_rows_with_headers,
    _scroll_positions,
)


def test_parse_rows_with_headers_maps_product_id_and_metrics():
    raw_rows = [
        {
            "product_id": "967084305452",
            "header_values": {
                "成交花费(元)": "12.50",
                "交易额(元)": "88.00",
                "实际投产比": "7.04",
                "总花费(元)": "12.50",
            },
            "row_text": "粉色包 商品ID：967084305452 ...",
        }
    ]
    parsed = _parse_rows_with_headers(raw_rows, [])
    assert len(parsed) == 1
    assert parsed[0]["product_id"] == "967084305452"
    assert parsed[0]["metrics"]["成交花费(元)"] == "12.50"
    assert parsed[0]["metrics"]["交易额(元)"] == "88.00"
    assert parsed[0]["metrics"]["实际投产比"] == "7.04"


def test_parse_rows_keeps_zero_values():
    raw_rows = [
        {
            "product_id": "967084305452",
            "header_values": {
                "成交花费(元)": "0.00",
                "交易额(元)": "0.00",
                "实际投产比": "0.00",
                "总花费(元)": "0.00",
                "净成交笔数": "0",
                "曝光量": "0",
            },
            "row_text": "商品 ID: 967084305452",
        }
    ]
    parsed = _parse_rows_with_headers(raw_rows, [])
    metrics = parsed[0]["metrics"]
    assert metrics["成交花费(元)"] == "0.00"
    assert metrics["净成交笔数"] == "0"
    assert metrics["曝光量"] == "0"


def test_parse_rows_maps_amount_alias_to_spend_column():
    raw_rows = [
        {
            "product_id": "967084305452",
            "header_values": {
                "成交金额(元)": "0.00",
                "结算[元]": "0.00",
            },
            "row_text": "",
        }
    ]
    parsed = _parse_rows_with_headers(raw_rows, [])
    metrics = parsed[0]["metrics"]
    assert metrics["成交花费(元)"] == "0.00"
    assert metrics["结算成交花费(元)"] == "0.00"


def test_parse_rows_filters_junk_metric_values():
    raw_rows = [
        {
            "product_id": "968644622706",
            "header_values": {
                "成交花费(元)": "0.00",
                "交易额(元)": "0.00",
                "操作": "详情 数据 更多",
                "推广状态": "手动暂停 去开启",
                "预算及出价": "预算日限额 ： 不限 净目标投产比 ： 3.25",
                "商品描述": "爱心图案可爱文具袋 商品 ID：968644622706拼单价：30.00 元",
            },
            "row_text": "爱心图案可爱文具袋",
        }
    ]
    parsed = _parse_rows_with_headers(raw_rows, [])
    metrics = parsed[0]["metrics"]
    assert metrics == {"成交花费(元)": "0.00", "交易额(元)": "0.00"}
    assert "操作" not in metrics
    assert "推广状态" not in metrics


def test_normalize_traffic_metrics_skips_dash_only():
    metrics = normalize_traffic_metrics(
        {
            "成交花费(元)": "0.00",
            "交易额(元)": "-",
            "曝光量": "",
        }
    )
    assert metrics == {"成交花费(元)": "0.00"}


def test_default_traffic_metric_columns_match_pdd_38():
    from pdd_agent.integrations.feishu.traffic_metric_columns import DEFAULT_TRAFFIC_METRIC_COLUMNS

    assert len(DEFAULT_TRAFFIC_METRIC_COLUMNS) == 38
    assert "结算成交花费(元)" not in DEFAULT_TRAFFIC_METRIC_COLUMNS
    assert DEFAULT_TRAFFIC_METRIC_COLUMNS[11] == "结算交易额(元)"


def test_scroll_positions_includes_end():
    assert _scroll_positions(0, 400) == [0]
    assert _scroll_positions(1000, 400) == [0, 400, 800, 1000]
