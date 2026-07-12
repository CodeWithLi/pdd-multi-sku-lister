"""上架前校验。"""

from __future__ import annotations

from pathlib import Path

from dy_agent.core.config import YamlSettings, load_yaml_settings
from dy_agent.domain.models import PreflightIssue, PreflightReport
from dy_agent.skills.listing.catalog import resolve_assets_root, resolve_listing_units


def run_preflight(
    product_codes: list[str],
    settings: YamlSettings | None = None,
    *,
    assets_root: Path | None = None,
) -> PreflightReport:
    settings = settings or load_yaml_settings()
    root = resolve_assets_root(settings, assets_root)
    issues: list[PreflightIssue] = []

    if not root.is_dir():
        issues.append(
            PreflightIssue(
                level="error",
                message=f"素材根目录不存在: {root}",
                reason_code="assets_root_missing",
            )
        )
        return PreflightReport(units=[], issues=issues)

    units = resolve_listing_units(product_codes, settings, assets_root=root)
    found_codes = {u.product_code.upper() for u in units}
    for code in product_codes:
        if code.upper() not in found_codes:
            issues.append(
                PreflightIssue(
                    level="error",
                    message=f"未找到商品目录: {code}",
                    listing_label=code,
                    reason_code="product_dir_missing",
                )
            )

    for unit in units:
        if not unit.carousel_images:
            issues.append(
                PreflightIssue(
                    level="error",
                    message="缺少主图",
                    listing_label=unit.listing_label,
                    reason_code="carousel_missing",
                )
            )
        if not unit.skus:
            issues.append(
                PreflightIssue(
                    level="error",
                    message="缺少 SKU 预览图",
                    listing_label=unit.listing_label,
                    reason_code="sku_preview_missing",
                )
            )
        for warning in unit.warnings:
            issues.append(
                PreflightIssue(
                    level="warning",
                    message=warning,
                    listing_label=unit.listing_label,
                    reason_code="catalog_warning",
                )
            )

    return PreflightReport(units=units, issues=issues)
