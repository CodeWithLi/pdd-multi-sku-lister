"""PDD 上传日志飞书字段映射与行解析单元测试。"""

from __future__ import annotations

from datetime import datetime

from pdd_agent.integrations.feishu.config import FeishuConfig, PddUploadLogConfig
from pdd_agent.integrations.feishu.pdd_upload_sync import build_pdd_upload_log_fields
from pdd_agent.skills.listing.goods_list_capture import (
    extract_list_status_from_text,
    parse_goods_list_row_meta,
)


def test_parse_goods_list_row_meta_extracts_created_at_and_status():
    row_text = """
    可爱草莓软糯造型毛绒零钱包
    ID: 966965874378
    商家编码: BD737A
    2026-06-16 13:21
    销售中
    """
    meta = parse_goods_list_row_meta(row_text)
    assert meta["matched_created_at"] == "2026-06-16 13:21:00"
    assert meta["list_status"] == "销售中"


def test_extract_list_status_from_text():
    assert extract_list_status_from_text("2026-06-16 13:21\n销售中") == "销售中"
    assert extract_list_status_from_text("已驳回") == "已驳回"


def test_build_pdd_upload_log_fields_maps_seven_columns():
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_upload_log=PddUploadLogConfig(
            enabled=True,
            table_id="tbldwkpLuvBVwc9",
        ),
    )
    verified_at = datetime(2026, 6, 16, 13, 25, 0)
    fields = build_pdd_upload_log_fields(
        config=cfg,
        title="可爱草莓软糯造型毛绒零钱包",
        merchant_code="BD737A",
        product_id="966965874378",
        product_link="https://mobile.yangkeduo.com/goods.html?goods_id=966965874378",
        list_status="销售中",
        created_at_raw="2026-06-16 13:21",
        verified_at=verified_at,
    )

    assert fields["宝贝标题"] == "可爱草莓软糯造型毛绒零钱包"
    assert fields["商品编码"] == "BD737A"
    assert fields["状态"] == "销售中"
    assert fields["商品id"] == "966965874378"
    assert isinstance(fields["日期"], int)
    assert isinstance(fields["创建时间"], int)
    assert "966965874378" in fields["商品链接"]["link"]
