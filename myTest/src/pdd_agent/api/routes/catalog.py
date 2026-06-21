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
    MaterialSource,
    get_product_detail,
    list_listing_target_options,
    list_products,
    run_preflight_api,
)
from pdd_agent.integrations.minio.client import check_minio_health
from pdd_agent.integrations.minio.config import load_minio_config, minio_configured
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.skills.listing.catalog import list_image_sets, parse_all_listings

router = APIRouter(prefix="/catalog", tags=["catalog"])

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _safe_asset_image_path(raw_path: str, *, material_source: MaterialSource = "local") -> Path:
    settings = load_yaml_settings()
    roots = [settings.paths.resolve("assets_root")]
    if material_source == "minio":
        from pdd_agent.integrations.minio.config import minio_cache_root

        roots.insert(0, minio_cache_root())
    target = Path(raw_path)
    if not target.is_absolute():
        resolved = None
        for root in roots:
            candidate = (root / target).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            resolved = candidate
            break
        if resolved is None:
            resolved = (roots[0] / target).resolve()
        target = resolved
    else:
        target = target.resolve()

    allowed = False
    for root in roots:
        try:
            target.relative_to(root)
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        raise HTTPException(status_code=403, detail="asset path is outside allowed assets roots")

    if target.suffix.lower() not in IMAGE_EXTS:
        raise HTTPException(status_code=400, detail="only image assets can be viewed")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"asset not found: {raw_path}")
    return target


@router.get("/products", response_model=list[ProductSummaryOut])
def catalog_products(material_source: MaterialSource = "local"):
    """扫描素材目录或 MinIO 下所有商品编码。"""
    source = material_source if material_source in {"local", "minio"} else "local"
    if source == "minio" and not minio_configured():
        raise HTTPException(status_code=503, detail="MinIO 未配置，请填写 config/minio.yaml")
    return list_products(material_source=source)


@router.get("/listing-targets", response_model=list[ListingTargetOptionOut])
def catalog_listing_targets(
    account_id: str = "",
    material_source: MaterialSource = "local",
):
    """列出上架任务可选的素材分组；传 account_id 时附带该店已上架商品标记。"""
    source = material_source if material_source in {"local", "minio"} else "local"
    if source == "minio" and not minio_configured():
        raise HTTPException(status_code=503, detail="MinIO 未配置，请填写 config/minio.yaml")
    return list_listing_target_options(
        account_id=account_id.strip(),
        material_source=source,
    )


@router.get("/minio/health")
def catalog_minio_health():
    """MinIO 连接状态。"""
    cfg = load_minio_config()
    health = check_minio_health(cfg)
    health["listing_poll_seconds"] = cfg.listing_poll_seconds
    health["alist_url"] = cfg.alist_url
    health["console_url"] = cfg.console_url
    health["cache_root"] = str(cfg.cache_root)
    return health


@router.get("/products/{product_code}", response_model=ProductDetailOut)
def catalog_product_detail(product_code: str, material_source: MaterialSource = "local"):
    """解析单个商品的全部套图与 SKU。"""
    source = material_source if material_source in {"local", "minio"} else "local"
    if source == "minio" and not minio_configured():
        raise HTTPException(status_code=503, detail="MinIO 未配置，请填写 config/minio.yaml")
    detail = get_product_detail(product_code, material_source=source)
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
def catalog_asset(
    path: str = Query(..., min_length=1),
    material_source: MaterialSource = "local",
):
    """安全读取素材目录或 MinIO 缓存内的图片，用于前端预览。"""
    source = material_source if material_source in {"local", "minio"} else "local"
    return FileResponse(_safe_asset_image_path(path, material_source=source))


@router.post("/preflight", response_model=PreflightResponse)
def catalog_preflight(body: PreflightRequest):
    """上架前校验（不打开浏览器）。"""
    source = body.material_source if body.material_source in {"local", "minio"} else "local"
    if source == "minio" and not minio_configured():
        raise HTTPException(status_code=503, detail="MinIO 未配置，请填写 config/minio.yaml")
    return run_preflight_api(body.product_codes, material_source=source)
