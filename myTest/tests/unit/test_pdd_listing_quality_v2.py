"""独立拼多多上架修复流程测试。"""

from __future__ import annotations

from types import SimpleNamespace

import yaml

from pdd_agent.domain.models import ListingUnit
from pdd_agent.skills.listing import catalog as catalog_mod
from pdd_agent.skills.listing import spec_labels
from pdd_agent.skills.listing.listing_accessory_cost_pricing import (
    activate_accessory_cost_pricing,
    deactivate_accessory_cost_pricing,
    resolve_accessory_cost_pricing,
)
from pdd_agent.skills.listing.listing_price_float import reset_listing_price_float_registry
from pdd_agent.skills.listing.pdd_listing_quality_v2 import (
    fixed_price_mode_enabled,
    generate_compliant_title,
    prefer_product_type_size_label,
    preview_dedupe_key,
    quality_v2_enabled,
    run_quality_v2_publish_search,
    save_quality_v2_enabled,
    validate_quality_v2_title,
)
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry


def _cfg(*, quality_v2: bool = False, original_sum: bool = False):
    return SimpleNamespace(
        pipeline=SimpleNamespace(
            pdd_listing_quality_v2_enabled=quality_v2,
            original_sum_pricing_enabled=original_sum,
            accessory_cost_pricing_enabled=False,
            accessory_cost_tiered_float_enabled=False,
        )
    )


def test_quality_v2_switch_defaults_off_and_preserves_old_pipeline_values(tmp_path):
    path = tmp_path / "feishu.yaml"
    path.write_text(
        "pipeline:\n  original_sum_pricing_enabled: false\n  accessory_cost_pricing_enabled: true\n",
        encoding="utf-8",
    )

    save_quality_v2_enabled(True, path)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["pipeline"]["pdd_listing_quality_v2_enabled"] is True
    assert data["pipeline"]["original_sum_pricing_enabled"] is False
    assert data["pipeline"]["accessory_cost_pricing_enabled"] is True
    assert quality_v2_enabled(_cfg()) is False
    assert quality_v2_enabled(_cfg(quality_v2=True)) is True


def test_quality_v2_enables_fixed_component_price_path():
    from pdd_agent.integrations.feishu.config import accessory_style_pricing_enabled

    assert accessory_style_pricing_enabled(_cfg(quality_v2=True)) is True


def test_quality_v2_title_policy_length_punctuation_and_banned_terms():
    assert validate_quality_v2_title("可" * 25).valid
    assert not validate_quality_v2_title("可" * 24).valid
    assert not validate_quality_v2_title("可" * 30).valid
    assert "标点" in "".join(validate_quality_v2_title("可" * 24 + "！").reasons)
    assert "禁用词" in "".join(validate_quality_v2_title("可" * 23 + "官方").reasons)


def test_quality_v2_title_regenerates_until_compliant():
    candidates = ["长" * 30, "合" * 25]
    prompts: list[str] = []

    def _invoke(prompt: str):
        prompts.append(prompt)
        return {"title": candidates.pop(0), "source": "primary"}

    result = generate_compliant_title(base_prompt="生成标题", invoke=_invoke)

    assert result["title"] == "合" * 25
    assert len(prompts) == 2
    assert "上一次标题" in prompts[1]
    assert result["quality_v2_title_valid"] is True


def test_quality_v2_title_does_not_fall_back_after_retry_exhaustion():
    result = generate_compliant_title(
        base_prompt="生成标题",
        invoke=lambda _prompt: {"title": "短标题", "source": "primary"},
    )

    assert result["title"] == ""
    assert result["policy_failed"] is True
    assert result["reason"] == "title_policy_retries_exhausted"
    assert len(result["quality_v2_attempts"]) == 3


def test_quality_v2_bundle_dedupe_uses_actual_components():
    old_a = preview_dedupe_key("BD032D", "套装", "BD032D+YKL020A+YKL004L", enabled=False)
    old_b = preview_dedupe_key("BD032D", "套装", "BD032D+YKL007P+YKL004L", enabled=False)
    new_a = preview_dedupe_key("BD032D", "套装", "BD032D+YKL020A+YKL004L", enabled=True)
    new_b = preview_dedupe_key("BD032D", "套装", "BD032D+YKL007P+YKL004L", enabled=True)

    assert old_a == old_b == ("BD032D", "套装")
    assert new_a != new_b


def test_catalog_keeps_multiple_bundle_materials_only_in_quality_v2(monkeypatch, tmp_path):
    previews = [
        tmp_path / "BD032D+YKL020A+YKL004L.png",
        tmp_path / "BD032D+YKL007P+YKL004L.png",
    ]
    monkeypatch.setattr(
        catalog_mod,
        "_resolve_sku_pricing_or_warn",
        lambda *_args, **_kwargs: ("10", "10", "11"),
    )

    def _parse(enabled: bool) -> ListingUnit:
        monkeypatch.setattr(catalog_mod, "quality_v2_enabled", lambda: enabled)
        unit = ListingUnit(product_code="BD032D", image_set="第一套图", root=tmp_path)
        catalog_mod._append_skus_from_previews(
            unit,
            previews,
            "BD032D",
            {},
            {},
            include_excel_missing_previews=True,
            seen_combo_keys=set(),
        )
        return unit

    assert len(_parse(False).skus) == 1
    assert [sku.combo_folder for sku in _parse(True).skus] == [path.stem for path in previews]


def test_quality_v2_prefers_product_type_for_doll_code(monkeypatch, tmp_path):
    catalog = {
        "BD064A": PddProductEntry("BD064A", "米色笔袋", "笔袋"),
        "GJ706A": PddProductEntry("GJ706A", "厨师挂件", "公仔"),
    }
    sku = catalog_mod.SkuCombo(
        style_code="BD064A",
        style_name="BD064A",
        model_code="GJ706A",
        model_name="",
        combo_folder="BD064A+GJ706A",
        preview_image=tmp_path / "preview.png",
    )
    monkeypatch.setattr(spec_labels, "quality_v2_enabled", lambda: True)

    spec_labels.apply_spec_labels_to_sku(sku, {"BD064A": "米色"}, catalog, {"GJ706A": "挂件"})

    assert sku.model_name == "笔袋+公仔"
    assert (
        prefer_product_type_size_label(
            base_entry=catalog["BD064A"],
            sub_entry=catalog["GJ706A"],
            fallback="笔袋+挂件",
        )
        == "笔袋+公仔"
    )


def test_quality_v2_fixed_price_uses_feishu_values_without_float():
    reset_listing_price_float_registry(enabled=False, single_float_min=0.0, single_float_max=0.0)
    activate_accessory_cost_pricing(cost_map={"YKL020A": 2.0}, original_sum=True)
    try:
        catalog = {
            "BD032D": PddProductEntry("BD032D", "樱桃蛋糕笔袋", "笔袋", 100, 9.7),
        }
        _, group_price, _ = resolve_accessory_cost_pricing(
            "BD032D",
            "YKL020A",
            catalog,
            {},
        )
    finally:
        deactivate_accessory_cost_pricing()

    assert fixed_price_mode_enabled(_cfg(quality_v2=True, original_sum=False)) is True
    assert group_price == "11.7"


def test_quality_v2_publish_search_reports_publishing_instead_of_missing_link():
    searched: list[str] = []

    def _search(step):
        searched.append(step.tab_text)
        if step.tab_key == "publishing":
            return {"status": "captured", "pdd_product_id": "123"}
        return {"status": "not_found"}

    result = run_quality_v2_publish_search(
        search_tab=_search,
        search_all=lambda: {"status": "not_found"},
    )

    assert result["status"] == "publishing"
    assert searched == ["在售中", "发布中"]


def test_quality_v2_publish_search_explains_when_no_link_exists():
    result = run_quality_v2_publish_search(
        search_tab=lambda _step: {"status": "not_found"},
        search_all=lambda: {"status": "not_found"},
    )

    assert result["status"] == "not_found"
    assert result["searched_tabs"] == ["在售中", "发布中", "已驳回", "草稿箱", "全部"]
    assert "没有可复制的商品链接" in result["message"]


def test_quality_v2_api_switch_is_independent(monkeypatch):
    from pdd_agent.api.routes import pipelines
    from pdd_agent.api.schemas.pipelines import PipelinePddListingQualityV2UpdateIn

    saved: list[bool] = []
    monkeypatch.setattr(pipelines, "save_quality_v2_enabled", saved.append)
    monkeypatch.setattr(pipelines, "quality_v2_enabled", lambda: saved[-1] if saved else False)
    monkeypatch.setattr(pipelines, "_clear_excel_data_caches", lambda: None)

    result = pipelines.update_integrated_pdd_listing_quality_v2(
        PipelinePddListingQualityV2UpdateIn(enabled=True)
    )

    assert saved == [True]
    assert result.enabled is True
