"""规格标签：尺寸分组 + 商品表解析。"""

from pathlib import Path

from pdd_agent.skills.listing.pdd_product_catalog import (
    PddProductEntry,
    infer_sub_product_category,
    load_pdd_product_catalog,
    resolve_size_label,
)
from pdd_agent.skills.listing.spec_labels import apply_spec_labels_to_sku
from pdd_agent.domain.models import SkuCombo


def test_infer_sub_product_category_keywords():
    assert infer_sub_product_category(PddProductEntry("YKL001N", "睡觉卡皮巴拉挂件", "亚克力")) == "挂件"
    assert infer_sub_product_category(PddProductEntry("YKL008E", "蜡笔小新摇摇乐尺子", "亚克力")) == "尺子"


def test_resolve_size_label_groups_combo_types():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "蓝色蝴蝶结", "笔袋"),
        "BD716B": PddProductEntry("BD716B", "紫色蝴蝶结", "笔袋"),
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


def test_apply_spec_labels_to_sku():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "蓝色蝴蝶结", "笔袋"),
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
    apply_spec_labels_to_sku(sku, {"BD716A": "白色"}, catalog)
    assert sku.style_name == "白色"
    assert sku.model_name == "笔袋+挂件"


def test_load_real_pdd_product_catalog():
    catalog = load_pdd_product_catalog()
    assert catalog
    assert "BD716A" in catalog
    assert catalog["YKL001N"].product_type == "亚克力"
