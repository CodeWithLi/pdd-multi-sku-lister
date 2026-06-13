"""规格标签：尺寸分组 + 商品表解析。"""

from pathlib import Path

from pdd_agent.skills.listing.pdd_product_catalog import (
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
