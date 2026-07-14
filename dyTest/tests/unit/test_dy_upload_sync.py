"""DY 发布日志字段构建单元测试。"""

from datetime import datetime
from pathlib import Path

from dy_agent.domain.models import SkuCombo
from dy_agent.integrations.feishu.config import DyUploadLogConfig, FeishuConfig
from dy_agent.integrations.feishu.dy_upload_spec_log import (
    build_dy_upload_spec_log_rows,
    listing_unit_sku_metadata,
)
from dy_agent.integrations.feishu.dy_upload_sync import (
    build_dy_upload_log_fields,
    resolve_listing_display_price,
)


def _cfg() -> FeishuConfig:
    return FeishuConfig(
        app_id="app",
        app_secret="secret",
        bitable_app_token="basexxx",
        dy_upload_log=DyUploadLogConfig(enabled=True),
    )


def test_build_dy_upload_log_fields_uses_shop_name_column():
    start = datetime(2026, 7, 14, 11, 0, 0)
    end = datetime(2026, 7, 14, 11, 2, 0)
    fields = build_dy_upload_log_fields(
        config=_cfg(),
        title="简约ins卡皮巴拉抽绳笔袋",
        merchant_code="BD021A卡皮巴拉笔袋",
        product_id="3831101898937729447",
        product_link="https://haohuo.jinritemai.com/ecommerce/trade/detail/index.html?id=3831101898937729447",
        account_name="测试店",
        price="14.20",
        publish_start=start,
        publish_end=end,
        verified_at=end,
    )
    assert fields["店铺名称"] == "测试店"
    assert fields["商品编码"] == "BD021A卡皮巴拉笔袋"
    assert fields["商品链接ID"] == "3831101898937729447"
    assert fields["价格"] == 14.2
    assert fields["耗时秒"] == 120.0
    assert fields["商品链接"]["link"].endswith("3831101898937729447")


def test_build_dy_upload_spec_log_rows_includes_combo_barcode():
    code = "BD025A面包小狗笔袋"
    skus = [
        listing_unit_sku_metadata(
            SkuCombo(
                style_code=code,
                style_name="面包小狗",
                model_code=code,
                model_name="单款",
                combo_folder=code,
                preview_image=Path("a.jpg"),
                price="16.49",
            )
        ),
        listing_unit_sku_metadata(
            SkuCombo(
                style_code=code,
                style_name="面包小狗",
                model_code="YKL001A",
                model_name="挂件",
                combo_folder=f"{code}+YKL001A",
                preview_image=Path("b.jpg"),
                price="18.88",
            )
        ),
    ]
    rows = build_dy_upload_spec_log_rows(
        merchant_code=code,
        listing_title="简约ins面包小狗笔袋",
        sku_rows=skus,
    )
    assert rows[0]["combo_barcode"] == ""
    assert rows[0]["row_kind"] == "summary"
    combo_rows = [r for r in rows if r["combo_barcode"]]
    assert combo_rows
    assert combo_rows[0]["combo_barcode"] == f"{code}+YKL001A"
    assert combo_rows[0]["price"] == "18.88"


def test_resolve_listing_display_price_uses_min_sku_price():
    skus = [
        SkuCombo(
            style_code="A",
            style_name="A",
            model_code="单款",
            model_name="单款",
            combo_folder="A",
            preview_image=Path("a.jpg"),
            price="21.22",
        ),
        SkuCombo(
            style_code="A",
            style_name="A",
            model_code="套装",
            model_name="套装",
            combo_folder="A+B",
            preview_image=Path("b.jpg"),
            price="14.20",
        ),
    ]
    assert resolve_listing_display_price(skus) == "14.20"
