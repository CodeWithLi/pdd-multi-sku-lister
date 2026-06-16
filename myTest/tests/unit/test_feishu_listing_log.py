"""飞书上架日志字段映射单元测试（不调用真实 API）。"""

from __future__ import annotations

from datetime import date, datetime

from pdd_agent.db.models import PublishedProductORM
from pdd_agent.integrations.feishu.config import FeishuConfig
from pdd_agent.integrations.feishu.listing_log import row_to_feishu_fields


def test_row_to_feishu_fields_maps_core_columns():
    row = PublishedProductORM(
        mapping_id="abc123",
        account_id="store_A",
        source_run_id="run1",
        product_code="BD046A",
        family_code="BD046",
        image_set="第一套",
        listing_label="BD046A/第一套",
        merchant_code="BD046A",
        pdd_product_id="123456789",
        spec_metadata={
            "skus": [
                {"group_price": "199.9", "single_price": "299.9"},
                {"group_price": "199.9", "single_price": "299.9"},
            ],
        },
        status="on_sale",
        published_at=datetime(2026, 6, 16, 15, 30, 0),
        created_at=datetime(2026, 6, 16, 15, 30, 0),
        updated_at=datetime(2026, 6, 16, 15, 30, 0),
    )
    cfg = FeishuConfig(app_id="x", app_secret="y", bitable_app_token="z")
    fields = row_to_feishu_fields(row, cfg, log_day=date(2026, 6, 16), minimal_fields=True)

    assert fields["商家编码"] == "BD046A"
    assert fields["规格数"] == 2
    assert fields["一口价"] == 199.9
    assert fields["状态"] == "在售"
    assert "映射ID" not in fields
    assert "link" in fields["商品链接"]
    assert "123456789" in fields["商品链接"]["link"]
