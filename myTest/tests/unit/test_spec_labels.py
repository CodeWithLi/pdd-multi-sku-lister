"""规格标签：尺寸分组 + 商品表解析。"""

from pathlib import Path

from pdd_agent.skills.listing.pdd_product_catalog import (
    BUNDLE_MODEL_CODE,
    PddProductEntry,
    fallback_sub_category_from_spec,
    infer_sub_product_category,
    infer_sub_product_category_rules,
    is_weak_sub_category,
    load_pdd_product_catalog,
    resolve_size_label,
)
from pdd_agent.skills.listing.spec_labels import apply_spec_labels_to_sku
from pdd_agent.domain.models import SkuCombo


def test_infer_sub_product_category_keywords():
    assert infer_sub_product_category(PddProductEntry("YKL001N", "睡觉卡皮巴拉挂件", "亚克力")) == "挂件"
    assert infer_sub_product_category(PddProductEntry("YKL008E", "蜡笔小新摇摇乐尺子", "亚克力")) == "尺子"
    assert infer_sub_product_category(PddProductEntry("YKL004I", "loopy海狸套尺", "亚克力")) == "套尺"
    assert infer_sub_product_category(PddProductEntry("YKL020A", "白色磁吸夹", "亚克力")) == "磁吸夹"
    assert infer_sub_product_category(PddProductEntry("X1", "大号财神冰箱贴", "亚克力")) == "冰箱贴"
    assert infer_sub_product_category(PddProductEntry("X2", "翘耳帕恰狗PP夹【双面】", "亚克力")) == "PP夹"


def test_infer_sub_product_category_uses_meaningful_product_type():
    assert infer_sub_product_category_rules(PddProductEntry("BD999A", "某款", "公仔")) == "公仔"
    assert infer_sub_product_category_rules(PddProductEntry("BD999B", "某款", "拖鞋")) == "拖鞋"


def test_is_weak_sub_category():
    assert is_weak_sub_category("亚克力")
    assert is_weak_sub_category("")
    assert not is_weak_sub_category("挂件")
    assert not is_weak_sub_category("笔袋")


def test_fallback_sub_category_from_spec():
    entry = PddProductEntry("C1", "亚克力定制款支配之剑(单片)", "亚克力")
    assert fallback_sub_category_from_spec(entry) == "支配之剑"


def test_resolve_size_label_groups_combo_types():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋"),
        "BD716B": PddProductEntry("BD716B", "黑色笔袋", "笔袋"),
        "BD888A": PddProductEntry("BD888A", "某公仔", "公仔"),
        "YKL001N": PddProductEntry("YKL001N", "睡觉卡皮巴拉挂件", "亚克力"),
        "YKL001AC": PddProductEntry("YKL001AC", "粉猪头挂件", "亚克力"),
        "YKL008E": PddProductEntry("YKL008E", "蜡笔小新摇摇乐尺子", "亚克力"),
        "YKL008A": PddProductEntry("YKL008A", "帕恰狗摇摇乐尺子", "亚克力"),
    }
    assert resolve_size_label("BD716A", "BD716A", catalog) == "笔袋"
    assert resolve_size_label("BD716A", "YKL001N", catalog) == "笔袋+挂件"
    assert resolve_size_label("BD716B", "YKL001AC", catalog) == "笔袋+挂件"
    assert resolve_size_label("BD716A", "YKL008E", catalog) == "笔袋+尺子"
    assert resolve_size_label("BD716B", "YKL008A", catalog) == "笔袋+尺子"
    assert resolve_size_label("BD888A", "BD888A", catalog) == "公仔"
    catalog.update(
        {
            "YKL004I": PddProductEntry("YKL004I", "loopy海狸套尺", "亚克力"),
            "YKL031D": PddProductEntry("YKL031D", "粉色草莓kt猫套尺", "亚克力"),
            "YKL020A": PddProductEntry("YKL020A", "白色磁吸夹", "亚克力"),
        }
    )
    assert resolve_size_label("BD716A", "YKL004I", catalog) == "笔袋+套尺"
    assert resolve_size_label("BD716B", "YKL031D", catalog) == "笔袋+套尺"
    assert resolve_size_label("BD716A", "YKL020A", catalog) == "笔袋+磁吸夹"
    assert resolve_size_label("BD716B", "YKL020A", catalog) == "笔袋+磁吸夹"
    assert resolve_size_label("BD716A", BUNDLE_MODEL_CODE, catalog) == "笔袋+套装"
    assert resolve_size_label("BD716B", BUNDLE_MODEL_CODE, catalog) == "笔袋+套装"


def test_resolve_size_label_uses_sub_category_cache():
    catalog = {
        "BD100A": PddProductEntry("BD100A", "某笔袋", "笔袋"),
        "YKL999Z": PddProductEntry("YKL999Z", "亚克力定制萌字", "亚克力"),
    }
    cache = {"YKL999Z": "贴纸"}
    assert resolve_size_label("BD100A", "YKL999Z", catalog, sub_category_cache=cache) == "笔袋+贴纸"


def test_disambiguate_style_colors_when_ai_duplicates():
    from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry
    from pdd_agent.skills.listing.spec_labels import disambiguate_style_colors

    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色左小狗右开窗笔袋", "笔袋"),
        "BD716B": PddProductEntry("BD716B", "黑色左小狗右开窗笔袋", "笔袋"),
    }
    colors = {"BD716A": "白色", "BD716B": "白色"}
    fixed = disambiguate_style_colors(colors, catalog)
    assert fixed["BD716A"] != fixed["BD716B"]
    assert fixed["BD716A"] == "灰色"
    assert fixed["BD716B"] == "黑色"


def test_reconcile_style_color_with_catalog_fixes_white_misread():
    from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry
    from pdd_agent.skills.listing.spec_labels import reconcile_style_color_with_catalog

    entry_a = PddProductEntry("BD716A", "灰色左小狗右开窗笔袋", "笔袋")
    entry_b = PddProductEntry("BD716B", "黑色左小狗右开窗笔袋", "笔袋")
    entry_c = PddProductEntry("BD716C", "绿色左小狗右开窗笔袋", "笔袋")

    assert reconcile_style_color_with_catalog("白色", entry_a) == ("灰色", "ai+catalog")
    assert reconcile_style_color_with_catalog("白色", entry_b) == ("黑色", "ai+catalog")
    assert reconcile_style_color_with_catalog("绿色", entry_c) == ("绿色", "ai")


def test_ordered_style_names_keeps_all_siblings():
    from pdd_agent.domain.models import ListingUnit, SkuCombo
    from pdd_agent.skills.listing.spec_labels import ordered_style_names
    from pathlib import Path

    unit = ListingUnit(product_code="BD716A", image_set="第一套图", root=Path("."))
    unit.style_codes = ["BD716A", "BD716B", "BD716C"]
    unit.skus = [
        SkuCombo(
            style_code="BD716A",
            style_name="灰色",
            model_code="BD716A",
            model_name="笔袋",
            combo_folder="BD716A",
            preview_image=Path("a.png"),
        ),
        SkuCombo(
            style_code="BD716B",
            style_name="黑色",
            model_code="BD716B",
            model_name="笔袋",
            combo_folder="BD716B",
            preview_image=Path("b.png"),
        ),
        SkuCombo(
            style_code="BD716C",
            style_name="绿色",
            model_code="BD716C",
            model_name="笔袋",
            combo_folder="BD716C",
            preview_image=Path("c.png"),
        ),
    ]
    assert ordered_style_names(unit) == ["灰色", "黑色", "绿色"]


def test_pick_style_reference_image_uses_solo_file_only(tmp_path):
    from pdd_agent.domain.models import ListingUnit, SkuCombo
    from pdd_agent.skills.listing.spec_labels import pick_style_reference_image

    set_dir = tmp_path / "BD716" / "第一套图"
    dir_a = set_dir / "BD716A"
    dir_b = set_dir / "BD716B"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)
    solo_a = dir_a / "BD716A.png"
    combo_a = dir_a / "BD716A+YKL001N.png"
    solo_b = dir_b / "BD716B.png"
    combo_b = dir_b / "BD716B+YKL001AC.png"
    for p in (solo_a, combo_a, solo_b, combo_b):
        p.write_bytes(b"img")

    unit = ListingUnit(product_code="BD716A", image_set="第一套图", root=dir_a)
    unit.skus = [
        SkuCombo(
            style_code="BD716A",
            style_name="BD716A",
            model_code="YKL001N",
            model_name="笔袋+挂件",
            combo_folder="BD716A+YKL001N",
            preview_image=combo_a,
        ),
        SkuCombo(
            style_code="BD716B",
            style_name="BD716B",
            model_code="YKL001AC",
            model_name="笔袋+挂件",
            combo_folder="BD716B+YKL001AC",
            preview_image=combo_b,
        ),
    ]
    unit.carousel_images = [dir_a / "1.png"]

    assert pick_style_reference_image(unit, "BD716A") == solo_a
    assert pick_style_reference_image(unit, "BD716B") == solo_b


def test_apply_spec_labels_to_sku():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋"),
        "YKL001N": PddProductEntry("YKL001N", "睡觉卡皮巴拉挂件", "亚克力"),
    }
    sku = SkuCombo(
        style_code="BD716A",
        style_name="BD716A",
        model_code="YKL001N",
        model_name="YKL001N",
        combo_folder="BD716A+YKL001N",
        preview_image=Path("x.png"),
    )
    apply_spec_labels_to_sku(sku, {"BD716A": "白色"}, catalog, {"YKL001N": "挂件"})
    assert sku.style_name == "白色"
    assert sku.model_name == "笔袋+挂件"


def test_load_real_pdd_product_catalog():
    catalog = load_pdd_product_catalog()
    assert catalog
    assert "BD716A" in catalog
    assert catalog["BD716A"].product_type == "笔袋"
    assert catalog["YKL001N"].product_type == "亚克力"
    assert catalog["YKL001N"].inventory > 0
    assert catalog["YKL001N"].price > 0


def test_append_product_type_to_size_label():
    from pdd_agent.skills.listing.pdd_product_catalog import append_product_type_to_size_label

    assert append_product_type_to_size_label("笔袋+挂件", "公仔") == "笔袋+挂件(公仔)"
    assert append_product_type_to_size_label("笔袋+挂件(公仔)", "公仔") == "笔袋+挂件(公仔)"
    assert append_product_type_to_size_label("笔袋+挂件", "") == "笔袋+挂件"


def test_disambiguate_size_labels_by_product_type():
    from pdd_agent.domain.models import ListingUnit
    from pdd_agent.skills.listing.spec_labels import disambiguate_size_labels

    unit = ListingUnit(product_code="BD719A", image_set="第一套图", root=Path("."))
    unit.style_codes = ["BD719A"]
    unit.skus = [
        SkuCombo(
            style_code="BD719A",
            style_name="蓝色",
            model_code="ABC123A",
            model_name="笔袋+挂件",
            combo_folder="BD719A+ABC123A",
            preview_image=Path("a.png"),
        ),
        SkuCombo(
            style_code="BD719A",
            style_name="蓝色",
            model_code="ABC123B",
            model_name="笔袋+挂件",
            combo_folder="BD719A+ABC123B",
            preview_image=Path("b.png"),
        ),
    ]
    catalog = {
        "BD719A": PddProductEntry("BD719A", "笔袋", "笔袋"),
        "ABC123A": PddProductEntry("ABC123A", "鲨鱼挂件", "公仔"),
        "ABC123B": PddProductEntry("ABC123B", "KT挂件", "钥匙扣"),
    }
    disambiguate_size_labels(unit, catalog)
    assert unit.skus[0].model_name == "笔袋+挂件(公仔)"
    assert unit.skus[1].model_name == "笔袋+挂件(钥匙扣)"


def test_disambiguate_size_labels_uses_ai_when_product_type_collides(monkeypatch):
    from pdd_agent.domain.models import ListingUnit
    from pdd_agent.skills.listing.spec_labels import disambiguate_size_labels

    unit = ListingUnit(product_code="BD719A", image_set="第一套图", root=Path("."))
    unit.style_codes = ["BD719A", "BD719B"]
    unit.skus = [
        SkuCombo(
            style_code="BD719A",
            style_name="蓝色",
            model_code="ABC123A",
            model_name="笔袋+挂件",
            combo_folder="BD719A+ABC123A",
            preview_image=Path("a.png"),
        ),
        SkuCombo(
            style_code="BD719A",
            style_name="蓝色",
            model_code="ABC123B",
            model_name="笔袋+挂件",
            combo_folder="BD719A+ABC123B",
            preview_image=Path("b.png"),
        ),
        SkuCombo(
            style_code="BD719B",
            style_name="灰色",
            model_code="ABC123C",
            model_name="笔袋+挂件",
            combo_folder="BD719B+ABC123C",
            preview_image=Path("c.png"),
        ),
        SkuCombo(
            style_code="BD719B",
            style_name="灰色",
            model_code="ABC123D",
            model_name="笔袋+挂件",
            combo_folder="BD719B+ABC123D",
            preview_image=Path("d.png"),
        ),
    ]
    catalog = {
        "BD719A": PddProductEntry("BD719A", "笔袋", "笔袋"),
        "BD719B": PddProductEntry("BD719B", "笔袋", "笔袋"),
        "ABC123A": PddProductEntry("ABC123A", "鲨鱼挂件", "公仔"),
        "ABC123B": PddProductEntry("ABC123B", "KT挂件", "公仔"),
        "ABC123C": PddProductEntry("ABC123C", "鲨鱼灰", "公仔"),
        "ABC123D": PddProductEntry("ABC123D", "KT灰", "公仔"),
    }

    def fake_ai(style_code, skus, catalog):
        if style_code == "BD719A":
            return {
                "ABC123A": "笔袋+挂件(公仔-鲨鱼)",
                "ABC123B": "笔袋+挂件(公仔-KT)",
            }
        return {
            "ABC123C": "笔袋+挂件(公仔-鲨鱼)",
            "ABC123D": "笔袋+挂件(公仔-KT)",
        }

    monkeypatch.setattr(
        "pdd_agent.skills.listing.spec_labels.disambiguate_conflicting_size_labels_ai",
        fake_ai,
    )
    disambiguate_size_labels(unit, catalog)
    assert unit.skus[0].model_name == "笔袋+挂件(公仔-鲨鱼)"
    assert unit.skus[1].model_name == "笔袋+挂件(公仔-KT)"
    assert unit.skus[2].model_name == "笔袋+挂件(公仔-鲨鱼)"
    assert unit.skus[3].model_name == "笔袋+挂件(公仔-KT)"


def test_enrich_listing_unit_specs_dedupes_duplicate_display_rows(monkeypatch):
    from pdd_agent.domain.models import ListingUnit
    from pdd_agent.skills.listing import spec_labels
    from pdd_agent.skills.listing.spec_labels import enrich_listing_unit_specs

    unit = ListingUnit(product_code="BD719A", image_set="第一套图", root=Path("."))
    unit.style_codes = ["BD719A"]
    unit.skus = [
        SkuCombo(
            style_code="BD719A",
            style_name="BD719A",
            model_code="GJ361A",
            model_name="GJ361A",
            combo_folder="BD719A+GJ361A",
            preview_image=Path("a.png"),
        ),
        SkuCombo(
            style_code="BD719A",
            style_name="BD719A",
            model_code="YKL001A",
            model_name="YKL001A",
            combo_folder="BD719A+YKL001A",
            preview_image=Path("b.png"),
        ),
    ]

    catalog = {
        "BD719A": PddProductEntry("BD719A", "星星笔袋", "笔袋"),
        "GJ361A": PddProductEntry("GJ361A", "星星亚克力挂件", "公仔"),
        "YKL001A": PddProductEntry("YKL001A", "白色小铁挂件", "钥匙扣"),
    }

    monkeypatch.setattr(spec_labels, "get_pdd_product_catalog", lambda: catalog)
    monkeypatch.setattr(
        spec_labels,
        "resolve_style_colors",
        lambda unit, account_id="", allow_ai=True: {"BD719A": "蓝色"},
    )
    monkeypatch.setattr(spec_labels, "disambiguate_style_colors", lambda colors, catalog: colors)
    monkeypatch.setattr(spec_labels, "persist_style_color_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(spec_labels, "build_sub_category_cache", lambda unit, account_id="", allow_ai=True: {})

    enrich_listing_unit_specs(unit)

    assert len(unit.skus) == 2
    assert unit.skus[0].combo_folder == "BD719A+GJ361A"
    assert unit.skus[0].model_name == "笔袋+挂件(公仔)"
    assert unit.skus[1].model_name == "笔袋+挂件(钥匙扣)"


def test_resolve_combo_pricing_from_catalog():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 100, 20.0),
        "YKL001N": PddProductEntry("YKL001N", "挂件", "亚克力", 50, 30.0),
    }
    from pdd_agent.skills.listing.pdd_product_catalog import resolve_combo_pricing

    inv, gp, sp = resolve_combo_pricing("BD716A", "YKL001N", catalog, {})
    assert inv == "50"
    assert gp == "50"
    assert sp == "150"


def test_resolve_style_colors_uses_db_cache(monkeypatch, tmp_path):
    from pdd_agent.domain.models import ListingUnit
    from pdd_agent.skills.listing import spec_labels

    set_dir = tmp_path / "BD716" / "第一套图"
    dir_a = set_dir / "BD716A"
    dir_a.mkdir(parents=True)
    solo = dir_a / "BD716A.png"
    solo.write_bytes(b"img")

    unit = ListingUnit(product_code="BD716A", image_set="第一套图", root=dir_a)
    unit.style_codes = ["BD716A"]

    calls = {"ai": 0, "upsert": 0}

    def fake_get_cached(code, image_path=None):
        return "灰色" if code.upper() == "BD716A" else None

    def fake_detect(*args, **kwargs):
        calls["ai"] += 1
        return "白色"

    def fake_upsert(*args, **kwargs):
        calls["upsert"] += 1

    monkeypatch.setattr(spec_labels, "get_cached_style_color", fake_get_cached)
    monkeypatch.setattr(spec_labels, "detect_product_color", fake_detect)
    monkeypatch.setattr(spec_labels, "upsert_cached_style_color", fake_upsert)

    colors = spec_labels.resolve_style_colors(unit)
    assert colors["BD716A"] == "灰色"
    assert calls["ai"] == 0
    assert calls["upsert"] == 0
