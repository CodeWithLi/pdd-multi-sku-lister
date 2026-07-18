"""素材目录解析与 preflight 服务。"""

from pathlib import Path
from typing import Literal

from pdd_agent.api.schemas.catalog import (
    ListingTargetOptionOut,
    ListingUnitOut,
    PreflightIssueOut,
    PreflightResponse,
    ProductDetailOut,
    ProductSummaryOut,
    SkuComboOut,
)
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.domain.models import ListingUnit
from pdd_agent.skills.listing.catalog import (
    list_image_sets,
    list_listing_targets,
    list_listing_targets_from_root,
    list_product_codes,
    parse_all_listings,
)
from pdd_agent.skills.listing.preflight import run_preflight

MaterialSource = Literal["local", "minio"]


def _assets_root_for_source(material_source: MaterialSource) -> Path | None:
    if material_source == "minio":
        from pdd_agent.integrations.minio.config import minio_cache_root

        return minio_cache_root()
    return None


def _listing_targets_for_source(material_source: MaterialSource):
    settings = load_yaml_settings()
    if material_source == "minio":
        from pdd_agent.integrations.minio.config import (
            load_minio_config,
            minio_cache_root,
        )
        from pdd_agent.integrations.minio.catalog import list_minio_listing_targets

        cfg = load_minio_config()
        if not cfg.enabled:
            return list_listing_targets_from_root(minio_cache_root(cfg))
        return list_minio_listing_targets()
    return list_listing_targets(settings)


def _catalog_set_index_for_source(material_source: MaterialSource) -> dict[str, frozenset[str]]:
    return {
        item.selector: frozenset(item.product_codes)
        for item in _listing_targets_for_source(material_source)
    }


def _asset_path(path, assets_root) -> str:
    try:
        return str(path.resolve().relative_to(assets_root))
    except ValueError:
        return str(path)


def _unit_to_out(
    unit: ListingUnit,
    *,
    include_skus: bool = False,
    assets_root: Path | None = None,
) -> ListingUnitOut:
    settings = load_yaml_settings()
    root = assets_root or settings.paths.resolve("assets_root")
    skus: list[SkuComboOut] = []
    if include_skus:
        skus = [
            SkuComboOut(
                style_code=s.style_code,
                style_name=s.style_name,
                model_code=s.model_code,
                model_name=s.model_name,
                combo_folder=s.combo_folder,
                preview_image=_asset_path(s.preview_image, root),
                inventory=s.inventory,
                group_price=s.group_price,
                single_price=s.single_price,
            )
            for s in unit.skus
        ]
    return ListingUnitOut(
        product_code=unit.product_code,
        family_code=unit.family_code,
        image_set=unit.image_set,
        listing_label=unit.listing_label,
        merchant_code=unit.merchant_code,
        root=str(unit.root),
        carousel_images=[_asset_path(p, root) for p in unit.carousel_images],
        detail_images=[_asset_path(p, root) for p in unit.detail_images],
        material_image=_asset_path(unit.material_image, root) if unit.material_image else "",
        carousel_count=len(unit.carousel_images),
        detail_count=len(unit.detail_images),
        sku_count=len(unit.skus),
        style_codes=unit.style_codes,
        model_codes=unit.model_codes,
        warnings=unit.warnings,
        skus=skus,
    )


def list_products(*, material_source: MaterialSource = "local") -> list[ProductSummaryOut]:
    if material_source == "minio":
        from collections import defaultdict

        grouped: dict[str, set[str]] = defaultdict(set)
        for item in _listing_targets_for_source("minio"):
            for code in item.product_codes:
                grouped[code].add(item.image_set)
        summaries: list[ProductSummaryOut] = []
        for code in sorted(grouped):
            image_sets = sorted(grouped[code], key=lambda name: name)
            summaries.append(
                ProductSummaryOut(
                    product_code=code,
                    image_sets=image_sets,
                    listing_unit_count=len(image_sets),
                )
            )
        return summaries

    settings = load_yaml_settings()
    assets_root = settings.paths.resolve("assets_root")
    summaries: list[ProductSummaryOut] = []
    for code in list_product_codes(settings):
        image_sets = list_image_sets(code, assets_root)
        unit_count = len(image_sets) if image_sets else 1
        summaries.append(
            ProductSummaryOut(
                product_code=code,
                image_sets=image_sets,
                listing_unit_count=unit_count,
            )
        )
    return summaries


def list_listing_target_options(
    *,
    account_id: str = "",
    material_source: MaterialSource = "local",
) -> list[ListingTargetOptionOut]:
    from pdd_agent.api.services.listed_folder_service import listed_product_codes_by_set

    listed_by_set: dict[str, list[str]] = {}
    if account_id:
        listed_by_set = listed_product_codes_by_set(
            account_id,
            material_source=material_source,
        )

    options: list[ListingTargetOptionOut] = []
    for item in _listing_targets_for_source(material_source):
        current_codes = list(item.product_codes)
        listed_set = set(listed_by_set.get(item.selector, []))
        listed_codes = [code for code in current_codes if code in listed_set]
        unlisted_codes = [code for code in current_codes if code not in listed_set]
        options.append(
            ListingTargetOptionOut(
                selector=item.selector,
                family_code=item.family_code,
                image_set=item.image_set,
                product_codes=current_codes,
                product_count=len(current_codes),
                listed_product_codes=listed_codes,
                unlisted_product_codes=unlisted_codes,
                listed_count=len(listed_codes),
                unlisted_count=len(unlisted_codes),
                is_fully_listed=bool(current_codes) and not unlisted_codes,
                has_pending_listing=bool(unlisted_codes),
                is_material_ready=bool(current_codes),
            )
        )
    return options


def get_product_detail(
    product_code: str,
    *,
    material_source: MaterialSource = "local",
) -> ProductDetailOut | None:
    settings = load_yaml_settings()
    assets_root = _assets_root_for_source(material_source) or settings.paths.resolve("assets_root")
    if material_source == "minio":
        from pdd_agent.integrations.minio.config import load_minio_config
        from pdd_agent.integrations.minio.staging import stage_minio_for_product_codes

        if load_minio_config().enabled:
            stage_minio_for_product_codes([product_code])
    units = parse_all_listings(
        product_code,
        settings,
        include_excel_missing_previews=True,
        assets_root=assets_root if material_source == "minio" else None,
    )
    if not units:
        return None
    return ProductDetailOut(
        product_code=product_code,
        image_sets=list_image_sets(product_code, assets_root),
        units=[_unit_to_out(u, include_skus=True, assets_root=assets_root) for u in units],
    )


def run_preflight_api(
    product_codes: list[str],
    *,
    material_source: MaterialSource = "local",
) -> PreflightResponse:
    settings = load_yaml_settings()
    assets_root = _assets_root_for_source(material_source) or settings.paths.resolve("assets_root")
    report = run_preflight(
        product_codes,
        settings,
        include_excel_missing_previews=True,
        assets_root=assets_root if material_source == "minio" else None,
    )
    errors = sum(1 for i in report.issues if i.level == "error")
    warnings = sum(1 for i in report.issues if i.level == "warning")
    return PreflightResponse(
        ok=report.ok,
        unit_count=len(report.units),
        error_count=errors,
        warning_count=warnings,
        units=[_unit_to_out(u, include_skus=True, assets_root=assets_root) for u in report.units],
        issues=[
            PreflightIssueOut(
                level=i.level,
                message=i.message,
                listing_label=i.listing_label,
            )
            for i in report.issues
        ],
    )
