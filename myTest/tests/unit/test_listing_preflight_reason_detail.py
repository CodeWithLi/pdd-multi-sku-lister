"""预检 no_sku 原因细化。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.listing_preflight_reason_detail import infer_preflight_no_sku_brief


@patch("pdd_agent.api.services.listing_preflight_reason_detail.get_listing_feishu_snapshot")
def test_infer_preflight_no_sku_brief_feishu_query_failed(mock_snapshot):
    mock_snapshot.return_value = SimpleNamespace(source="feishu_query_failed")

    brief = infer_preflight_no_sku_brief(
        preflight={"units": [{"listing_label": "BD064A/第一套图", "warnings": []}]},
        listing_label="BD064A/第一套图",
        merchant_code="BD064A",
    )

    assert brief == "BD064A飞书查询异常，暂未取到商品数据"


@patch("pdd_agent.api.services.listing_preflight_reason_detail.get_listing_feishu_snapshot")
def test_infer_preflight_no_sku_brief_feishu_empty(mock_snapshot):
    mock_snapshot.return_value = SimpleNamespace(source="feishu_empty")

    brief = infer_preflight_no_sku_brief(
        preflight={"units": [{"listing_label": "BD064A/第一套图", "warnings": []}]},
        listing_label="BD064A/第一套图",
        merchant_code="BD064A",
    )

    assert brief == "BD064A飞书无商品数据"


@patch("pdd_agent.api.services.listing_preflight_reason_detail.get_listing_feishu_snapshot")
def test_infer_preflight_no_sku_brief_feishu_table_missing(mock_snapshot):
    mock_snapshot.return_value = SimpleNamespace(source="feishu_table_missing")

    brief = infer_preflight_no_sku_brief(
        preflight={"units": [{"listing_label": "BD064A/第一套图", "warnings": []}]},
        listing_label="BD064A/第一套图",
        merchant_code="BD064A",
    )

    assert brief == "BD064A飞书商品表未配置"


def test_infer_preflight_no_sku_brief_combo_subcode_from_warning():
    preflight = {
        "units": [
            {
                "listing_label": "AXBD001A/第一套图",
                "warnings": [
                    "[AXBD001A/第一套图] 组合图[AXBD001A+AXBD001B]商品表无子编码[AXBD001B]，不上架 AXBD001B.png",
                ],
            }
        ]
    }
    brief = infer_preflight_no_sku_brief(
        preflight=preflight,
        listing_label="AXBD001A/第一套图",
        merchant_code="AXBD001A",
    )
    assert brief == "AXBD001A下子图AXBD001A+AXBD001B飞书无此行"


@patch("pdd_agent.api.services.listing_preflight_reason_detail.get_listing_feishu_snapshot")
def test_infer_preflight_no_sku_brief_fallback_when_no_signal(mock_snapshot):
    mock_snapshot.return_value = SimpleNamespace(source="feishu")

    brief = infer_preflight_no_sku_brief(
        preflight={"units": [{"listing_label": "BD064A/第一套图", "warnings": []}]},
        listing_label="BD064A/第一套图",
        merchant_code="BD064A",
    )

    assert brief == "BD064A飞书无数据或名称未匹配"
