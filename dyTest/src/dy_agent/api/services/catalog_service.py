"""Catalog API service."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from dy_agent.core.config import load_yaml_settings
from dy_agent.integrations.minio.material import assets_root_for_material_source, normalize_material_source
from dy_agent.integrations.minio.staging import stage_minio_for_product_codes
from dy_agent.skills.listing.catalog import list_local_listing_targets, resolve_assets_root
from dy_agent.skills.listing.preflight import run_preflight

MaterialSource = Literal["local", "minio"]


def _assets_root_for_source(material_source: MaterialSource) -> Path | None:
    return assets_root_for_material_source(material_source)


def _listing_targets_for_source(material_source: MaterialSource) -> list[dict]:
    settings = load_yaml_settings()
    if material_source == "minio":
        from dy_agent.integrations.minio.catalog import list_minio_listing_targets

        return [
            {
                "selector": item.selector,
                "family_code": item.family_code,
                "image_set": item.image_set,
                "product_codes": list(item.product_codes),
                "product_count": item.product_count,
            }
            for item in list_minio_listing_targets()
        ]
    root = resolve_assets_root(settings)
    return list_local_listing_targets(root)


def list_listing_target_options(*, material_source: MaterialSource = "local") -> list[dict]:
    source = normalize_material_source(material_source)
    return _listing_targets_for_source(source)


def run_preflight_api(
    product_codes: list[str],
    *,
    material_source: MaterialSource = "local",
) -> dict:
    settings = load_yaml_settings()
    source = normalize_material_source(material_source)
    assets_root = _assets_root_for_source(source) or settings.paths.resolve("assets_root")

    if source == "minio":
        stage_minio_for_product_codes(product_codes)

    report = run_preflight(
        product_codes,
        settings,
        assets_root=assets_root if source == "minio" else None,
    )
    return report.model_dump(mode="json")
