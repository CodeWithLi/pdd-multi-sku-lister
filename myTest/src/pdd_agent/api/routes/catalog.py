"""素材目录与 preflight 接口。"""

from fastapi import APIRouter, HTTPException

from pdd_agent.api.schemas.catalog import (
    PreflightRequest,
    PreflightResponse,
    ProductDetailOut,
    ProductSummaryOut,
)
from pdd_agent.api.services.catalog_service import get_product_detail, list_products, run_preflight_api
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.skills.listing.catalog import list_image_sets

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/products", response_model=list[ProductSummaryOut])
def catalog_products():
    """扫描 data/assets 下所有商品编码。"""
    return list_products()


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
    if not (assets_root / product_code).is_dir():
        raise HTTPException(status_code=404, detail=f"product not found: {product_code}")
    return list_image_sets(product_code, assets_root)


@router.post("/preflight", response_model=PreflightResponse)
def catalog_preflight(body: PreflightRequest):
    """上架前校验（不打开浏览器）。"""
    return run_preflight_api(body.product_codes)
