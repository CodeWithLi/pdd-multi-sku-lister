"""Listing material source: MinIO sync + local cache paths."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from dy_agent.core.logging import get_logger
from dy_agent.integrations.minio.config import load_minio_config, minio_cache_root, minio_configured
from dy_agent.integrations.minio.staging import stage_minio_for_product_codes
from dy_agent.skills.listing.catalog import parse_listing_target_product_selector

MaterialSource = Literal["local", "minio"]
logger = get_logger(__name__)


def normalize_material_source(value: str | None) -> MaterialSource:
    raw = str(value or "").strip().lower()
    if raw == "minio":
        return "minio"
    if raw == "local":
        return "local"
    return resolve_default_material_source()


def resolve_default_material_source() -> MaterialSource:
    cfg = load_minio_config()
    default = str(cfg.default_material_source or "minio").strip().lower()
    if default == "local":
        return "local"
    if minio_configured(cfg):
        return "minio"
    return "local"


def product_codes_from_selectors(selectors: list[str]) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for raw in selectors:
        selector = str(raw or "").strip()
        if not selector:
            continue
        parsed = parse_listing_target_product_selector(selector)
        if parsed:
            code = parsed[2]
        elif "/" in selector:
            code = selector.rsplit("/", 1)[-1].strip()
        else:
            code = selector
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def prepare_listing_assets(
    product_codes: list[str],
    *,
    material_source: str | None = None,
) -> tuple[MaterialSource, Path | None]:
    source = normalize_material_source(material_source)
    if source != "minio":
        return "local", None
    if not minio_configured():
        raise RuntimeError("MinIO 未配置，请填写 config/minio.yaml")

    selectors = [str(code).strip() for code in product_codes if str(code).strip()]
    if not selectors:
        raise RuntimeError("无有效商品编码，无法从 MinIO 同步素材")

    cache_root = stage_minio_for_product_codes(selectors)
    stage_codes = product_codes_from_selectors(selectors) or selectors
    logger.info("minio listing assets ready codes=%s cache=%s", stage_codes, cache_root)
    return "minio", cache_root


def assets_root_for_material_source(source: MaterialSource) -> Path | None:
    if source == "minio":
        return minio_cache_root()
    return None
