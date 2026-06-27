"""聚水潭 ERP 库存读取单元测试。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.config import FeishuConfig, JushuitanErpInventoryConfig
from pdd_agent.integrations.feishu.jushuitan_erp_inventory import (
    apply_jushuitan_inventory_to_catalog,
    enrich_catalog_with_jushuitan_inventory,
)
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry, resolve_combo_pricing


def test_apply_jushuitan_inventory_overrides_catalog_stock():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 999, 20.0),
    }
    enriched = apply_jushuitan_inventory_to_catalog(
        catalog,
        {"BD716A": 88},
        enabled=True,
    )
    assert enriched["BD716A"].inventory == 88
    assert enriched["BD716A"].price == 20.0


def test_apply_jushuitan_inventory_zeros_missing_codes_when_map_loaded():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 999, 20.0),
    }
    enriched = apply_jushuitan_inventory_to_catalog(catalog, {"OTHER": 12}, enabled=True)
    assert enriched["BD716A"].inventory == 0


def test_apply_jushuitan_inventory_skips_when_map_empty():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 999, 20.0),
    }
    enriched = apply_jushuitan_inventory_to_catalog(catalog, {}, enabled=True)
    assert enriched["BD716A"].inventory == 999


def test_enrich_catalog_uses_provided_inventory_map():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 0, 20.0),
        "YKL001N": PddProductEntry("YKL001N", "挂架", "亚克力", 0, 5.0),
    }
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        jushuitan_erp_inventory=JushuitanErpInventoryConfig(enabled=True),
    )
    enriched = enrich_catalog_with_jushuitan_inventory(
        catalog,
        config=cfg,
        inventory_map={"BD716A": 50, "YKL001N": 30},
    )
    inv, _, _ = resolve_combo_pricing("BD716A", "YKL001N", enriched, {})
    assert inv == "30"
