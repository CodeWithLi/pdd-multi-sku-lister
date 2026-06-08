"""素材目录解析与 preflight 服务。"""

from pdd_agent.api.schemas.catalog import (
    ListingUnitOut,
    PreflightIssueOut,
    PreflightResponse,
    ProductDetailOut,
    ProductSummaryOut,
    SkuComboOut,
)
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.domain.models import ListingUnit
from pdd_agent.skills.listing.catalog import list_image_sets, list_product_codes, parse_all_listings
from pdd_agent.skills.listing.preflight import run_preflight


def _asset_path(path, assets_root) -> str:
    try:
        return str(path.resolve().relative_to(assets_root))
    except ValueError:
        return str(path)


def _unit_to_out(unit: ListingUnit, *, include_skus: bool = False) -> ListingUnitOut:
    settings = load_yaml_settings()
    assets_root = settings.paths.resolve("assets_root")
    skus: list[SkuComboOut] = []
    if include_skus:
        skus = [
            SkuComboOut(
                style_code=s.style_code,
                style_name=s.style_name,
                model_code=s.model_code,
                model_name=s.model_name,
                combo_folder=s.combo_folder,
                preview_image=_asset_path(s.preview_image, assets_root),
                inventory=s.inventory,
                group_price=s.group_price,
                single_price=s.single_price,
            )
            for s in unit.skus
        ]
    return ListingUnitOut(
        product_code=unit.product_code,
        image_set=unit.image_set,
        listing_label=unit.listing_label,
        merchant_code=unit.merchant_code,
        root=str(unit.root),
        carousel_images=[_asset_path(p, assets_root) for p in unit.carousel_images],
        detail_images=[_asset_path(p, assets_root) for p in unit.detail_images],
        carousel_count=len(unit.carousel_images),
        detail_count=len(unit.detail_images),
        sku_count=len(unit.skus),
        style_codes=unit.style_codes,
        model_codes=unit.model_codes,
        warnings=unit.warnings,
        skus=skus,
    )


def list_products() -> list[ProductSummaryOut]:
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


def get_product_detail(product_code: str) -> ProductDetailOut | None:
    settings = load_yaml_settings()
    assets_root = settings.paths.resolve("assets_root")
    if not (assets_root / product_code).is_dir():
        return None
    units = parse_all_listings(product_code, settings)
    return ProductDetailOut(
        product_code=product_code,
        image_sets=list_image_sets(product_code, assets_root),
        units=[_unit_to_out(u, include_skus=True) for u in units],
    )


def run_preflight_api(product_codes: list[str]) -> PreflightResponse:
    settings = load_yaml_settings()
    report = run_preflight(product_codes, settings)
    errors = sum(1 for i in report.issues if i.level == "error")
    warnings = sum(1 for i in report.issues if i.level == "warning")
    return PreflightResponse(
        ok=report.ok,
        unit_count=len(report.units),
        error_count=errors,
        warning_count=warnings,
        units=[_unit_to_out(u, include_skus=True) for u in report.units],
        issues=[
            PreflightIssueOut(
                level=i.level,
                message=i.message,
                listing_label=i.listing_label,
            )
            for i in report.issues
        ],
    )
