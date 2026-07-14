"""Catalog and preflight API routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dy_agent.api.services.catalog_service import list_listing_target_options, run_preflight_api
from dy_agent.integrations.minio.client import check_minio_health
from dy_agent.integrations.minio.config import load_minio_config, minio_poll_interval_seconds, minio_refresh_mode
from dy_agent.integrations.minio.material import normalize_material_source

router = APIRouter(prefix="/catalog", tags=["catalog"])


class ListingTargetOptionOut(BaseModel):
    selector: str
    family_code: str = ""
    image_set: str = ""
    product_codes: list[str] = Field(default_factory=list)
    product_count: int = 0


class PreflightRequest(BaseModel):
    product_codes: list[str] = Field(default_factory=list)
    material_source: Literal["local", "minio"] = "local"


@router.get("/listing-targets", response_model=list[ListingTargetOptionOut])
def listing_targets(
    material_source: Literal["local", "minio"] = Query("local"),
):
    source = normalize_material_source(material_source)
    if source == "minio":
        from dy_agent.integrations.minio.config import minio_configured

        if not minio_configured():
            raise HTTPException(status_code=503, detail="MinIO 未配置，请填写 config/minio.yaml")
    return list_listing_target_options(material_source=source)


@router.get("/minio/health")
def catalog_minio_health():
    cfg = load_minio_config()
    health = check_minio_health(cfg)
    health["listing_poll_seconds"] = minio_poll_interval_seconds(cfg)
    health["refresh_mode"] = minio_refresh_mode(cfg)
    return health


@router.post("/preflight")
def preflight(body: PreflightRequest):
    source = normalize_material_source(body.material_source)
    if source == "minio":
        from dy_agent.integrations.minio.config import minio_configured

        if not minio_configured():
            raise HTTPException(status_code=503, detail="MinIO 未配置，请填写 config/minio.yaml")
    return run_preflight_api(body.product_codes, material_source=source)
