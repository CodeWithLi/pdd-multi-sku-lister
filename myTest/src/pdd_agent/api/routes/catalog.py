"""素材目录与 preflight 接口。"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from pdd_agent.api.schemas.catalog import (
    ListingTargetOptionOut,
    PreflightRequest,
    PreflightResponse,
    ProductDetailOut,
    ProductSummaryOut,
)
from pdd_agent.api.services.catalog_service import (
    get_product_detail,
    list_listing_target_options,
    list_products,
    run_preflight_api,
)
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.skills.listing.catalog import list_image_sets, parse_all_listings

router = APIRouter(prefix="/catalog", tags=["catalog"])

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _safe_asset_image_path(raw_path: str) -> Path:
    settings = load_yaml_settings()
    assets_root = settings.paths.resolve("assets_root")
    target = Path(raw_path)
    if not target.is_absolute():
        target = (assets_root / target).resolve()
    else:
        target = target.resolve()

    try:
        target.relative_to(assets_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="asset path is outside assets_root")

    if target.suffix.lower() not in IMAGE_EXTS:
        raise HTTPException(status_code=400, detail="only image assets can be viewed")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"asset not found: {raw_path}")
    return target


@router.get("/products", response_model=list[ProductSummaryOut])
def catalog_products():
    """扫描 data/assets 下所有商品编码。"""
    return list_products()


@router.get("/listing-targets", response_model=list[ListingTargetOptionOut])
def catalog_listing_targets():
    """列出上架任务可选的素材分组，如 BD046/第一套。"""
    return list_listing_target_options()


@router.get("/products/{product_code}", response_model=ProductDetailOut)
def catalog_product_detail(product_code: str):
    """解析单个商品的全部套图与 SKU。"""
    detail = get_product_detail(product_code)
    if not detail:
        raise HTTPException(status_code=404, detail=f"product not found: {product_code}")
    return detail


@router.get("/products/{product_code}/image-sets", response_model=list[str])
def catalog_image_sets(product_code: str):
    """列出商品下的套图文件夹名。"""
    settings = load_yaml_settings()
    assets_root = settings.paths.resolve("assets_root")
    if not parse_all_listings(product_code, settings, include_excel_missing_previews=True):
        raise HTTPException(status_code=404, detail=f"product not found: {product_code}")
    return list_image_sets(product_code, assets_root)


@router.get("/asset")
def catalog_asset(path: str = Query(..., min_length=1)):
    """安全读取素材目录内的图片，用于前端预览。"""
    return FileResponse(_safe_asset_image_path(path))


@router.post("/preflight", response_model=PreflightResponse)
def catalog_preflight(body: PreflightRequest):
    """上架前校验（不打开浏览器）。"""
    return run_preflight_api(body.product_codes)
