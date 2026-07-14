"""配件成本定价写回抖音 SKU 字段。"""

from pathlib import Path

from dy_agent.domain.models import ListingUnit, SkuCombo
from dy_agent.skills.listing.listing_accessory_cost_float_registry import apply_reconciled_prices_to_unit
from dy_agent.skills.listing.pdd_product_catalog import PddProductEntry


def test_apply_reconciled_prices_updates_dy_price_fields():
    unit = ListingUnit(
        product_code="BD001A",
        family_code="BD001",
        image_set="第一套",
        root=Path("."),
        style_codes=["BD001A"],
        model_codes=["BD001A"],
        skus=[
            SkuCombo(
                style_code="BD001A",
                style_name="红色",
                model_code="BD001A",
                model_name="笔袋",
                combo_folder="BD001A",
                preview_image=Path("x.png"),
                price="0",
                market_price="0",
                inventory="0",
            )
        ],
    )
    catalog = {"BD001A": PddProductEntry(code="BD001A", color_spec="红色", product_type="笔袋", inventory=12, price=10)}

    apply_reconciled_prices_to_unit(
        unit,
        catalog,
        listing_scope="BD001/第一套",
        float_min=1,
        float_max=1,
        cost_map={},
        lookup_accessory_cost=lambda *args, **kwargs: 0,
        split_main_and_accessory_codes=lambda **kwargs: (kwargs["style_code"], []),
        bundle_model_code="套装",
        parse_combo_component_codes=lambda *args, **kwargs: [],
        resolve_inventory=lambda **kwargs: "12",
        format_price=lambda value: f"{float(value):.2f}",
        effective_single_price=lambda _scope, price: price + 5,
    )

    sku = unit.skus[0]
    assert sku.price == "11.00"
    assert sku.market_price == "16.00"
    assert sku.inventory == "12"
