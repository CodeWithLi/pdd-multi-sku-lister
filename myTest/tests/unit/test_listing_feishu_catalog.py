"""上架飞书编码匹配测试。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.listing_feishu_catalog import (
    catalog_entry,
    codes_match,
    collect_sub_sku_codes,
    is_sub_sku_code,
    normalize_listing_code,
    snapshot_record_fields,
)
from pdd_agent.integrations.feishu.listing_feishu_snapshot import ListingFeishuSnapshot
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry


def test_normalize_listing_code_preserves_chinese():
    assert normalize_listing_code("BD022A音乐小猫笔袋") == "BD022A音乐小猫笔袋"
    assert normalize_listing_code("  bd022a音乐  ") == "BD022A音乐"


def test_codes_match_hyphen_between_code_and_chinese():
    assert codes_match("BD021A-卡皮巴拉笔袋", "BD021A卡皮巴拉笔袋")
    assert codes_match("BD021A", "BD021A卡皮巴拉笔袋")


def test_codes_match_prefix_and_short():
    assert codes_match("BD022A", "BD022A音乐小猫笔袋")
    assert codes_match("BD022A音乐小猫笔袋", "BD022A")
    assert not codes_match("BD022A", "BD023A")


def test_snapshot_record_fields_fuzzy():
    snapshot = ListingFeishuSnapshot(
        records_by_code={
            "BD022A音乐小猫笔袋": {"商品编码": "BD022A音乐小猫笔袋", "颜色规格": "粉"},
        }
    )
    fields = snapshot_record_fields(snapshot, "BD022A")
    assert fields is not None
    assert fields["颜色规格"] == "粉"


def test_catalog_entry_fuzzy():
    catalog = {
        "BD736B毛绒笔袋": PddProductEntry(
            code="BD736B毛绒笔袋",
            color_spec="灰",
            product_type="笔袋",
        )
    }
    entry = catalog_entry(catalog, "BD736B")
    assert entry is not None
    assert entry.color_spec == "灰"


def test_is_sub_sku_code_only_accessories():
    assert is_sub_sku_code("YKL001N", "BD736B笔袋")
    assert not is_sub_sku_code("BD736B笔袋", "BD736B笔袋")
    assert not is_sub_sku_code("BD736A", "BD736B笔袋")


def test_collect_sub_sku_codes_from_unit():
    unit = type(
        "U",
        (),
        {
            "product_code": "BD736B毛绒笔袋",
            "model_codes": ["YKL001N", "BD736A", "YKL004F"],
        },
    )()
    assert collect_sub_sku_codes(unit) == ["YKL001N", "YKL004F"]
