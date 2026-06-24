"""素材目录与 preflight 接口。"""

import asyncio
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from pdd_agent.api.schemas.catalog import (
    ListingTargetOptionOut,
    MinioImageSetDeleteRequest,
    MinioImageSetDeleteResponse,
    MinioProductDeleteRequest,
    MinioProductDeleteResponse,
    MinioRefreshModeUpdate,
    MinioRabbitMQQueueUpdate,
    MinioTestUploadRequest,
    MinioSyncJobOut,
    MinioSyncStartRequest,
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
from pdd_agent.api.services.minio_sync_service import (
    get_active_minio_sync_job,
    get_minio_sync_job,
    start_minio_sync_job,
)
from pdd_agent.integrations.minio.alist_client import check_alist_health
from pdd_agent.integrations.minio.client import MinioAPIError, check_minio_health
from pdd_agent.integrations.minio.config import (
    load_minio_config,
    minio_configured,
    minio_poll_interval_seconds,
    minio_refresh_mode,
    save_minio_refresh_mode,
    save_rabbitmq_queue,
)
from pdd_agent.integrations.minio.broadcast import format_sse, subscribe_minio_events
from pdd_agent.integrations.minio.rabbitmq_admin import (
    check_rabbitmq_amqp,
    ensure_rabbitmq_binding,
    ensure_rabbitmq_queue,
    ensure_rabbitmq_setup,
    list_rabbitmq_queue_bindings,
    list_rabbitmq_queues,
    peek_rabbitmq_message,
)
from pdd_agent.integrations.minio.rabbitmq_consumer import (
    get_minio_rabbitmq_consumer,
    list_recent_rabbitmq_events,
)
from pdd_agent.integrations.minio.events import MinioUploadEvent
from pdd_agent.integrations.minio.folder_upload import UPLOAD_CATEGORIES, FolderUploadError, upload_folder_via_alist
from pdd_agent.integrations.minio.image_set_delete import (
    ImageSetDeleteError,
    delete_minio_image_set,
    delete_minio_product_folder,
)
from pdd_agent.integrations.minio.test_upload import upload_test_image_set
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
    health["listing_poll_seconds"] = minio_poll_interval_seconds(cfg)
    health["refresh_mode"] = minio_refresh_mode(cfg)
    health["alist_url"] = cfg.alist_url or cfg.alist.url
    health["console_url"] = cfg.console_url
    health["alist"] = check_alist_health(config=cfg)
    health["cache_root"] = str(cfg.cache_root)
    health["rabbitmq"] = get_minio_rabbitmq_consumer().status()
    health["rabbitmq"]["amqp"] = check_rabbitmq_amqp(cfg)
    from pdd_agent.integrations.redis.client import check_redis_health

    health["redis"] = check_redis_health()
    health["upload_categories"] = list(UPLOAD_CATEGORIES)
    return health


@router.put("/minio/refresh-mode")
def catalog_minio_refresh_mode_update(body: MinioRefreshModeUpdate):
    """切换素材发现方式：poll（定时轮询）与 rabbitmq（上传推送）互斥。"""
    mode = str(body.refresh_mode or "").strip().lower()
    if mode not in {"poll", "rabbitmq"}:
        raise HTTPException(status_code=400, detail="refresh_mode 只能是 poll 或 rabbitmq")
    try:
        saved = save_minio_refresh_mode(mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    consumer = get_minio_rabbitmq_consumer()
    consumer.restart()
    cfg = load_minio_config()
    return {
        "refresh_mode": saved,
        "listing_poll_seconds": minio_poll_interval_seconds(cfg),
        "rabbitmq": consumer.status(),
    }


@router.post("/minio/rabbitmq/ensure-queue")
def catalog_minio_rabbitmq_ensure_queue(queue: str = Query("", description="留空则用 PDD 默认队列")):
    """创建/确认 PDD 专用 RabbitMQ 队列，并恢复 MinIO 事件 binding。"""
    try:
        from pdd_agent.integrations.minio.config import DEFAULT_PDD_RABBITMQ_QUEUE

        target = str(queue or DEFAULT_PDD_RABBITMQ_QUEUE).strip()
        info = ensure_rabbitmq_setup(target)
        saved = save_rabbitmq_queue(target)
        consumer = get_minio_rabbitmq_consumer()
        consumer.restart()
        return {"saved_queue": saved, **info, "rabbitmq": consumer.status()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/minio/rabbitmq/ensure-binding")
def catalog_minio_rabbitmq_ensure_binding(
    queue: str = Query("", description="留空则用配置中的队列"),
    exchange: str = Query("", description="留空则用 minio.events"),
    routing_key: str = Query("", description="留空则用 beilemei.images"),
):
    """恢复 minio.events -> 队列 的 binding（Unbind 后一键启用）。"""
    try:
        info = ensure_rabbitmq_binding(queue=queue or None, exchange=exchange, routing_key=routing_key)
        bindings = list_rabbitmq_queue_bindings(queue=info["queue"])
        consumer = get_minio_rabbitmq_consumer()
        consumer.restart()
        return {**info, "bindings": bindings, "rabbitmq": consumer.status()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/minio/rabbitmq/bindings")
def catalog_minio_rabbitmq_bindings(queue: str = Query("", description="留空则用配置中的队列")):
    """查看队列 bindings，确认 minio.events 是否已绑定。"""
    try:
        return list_rabbitmq_queue_bindings(queue=queue or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/minio/rabbitmq/queues")
def catalog_minio_rabbitmq_queues():
    """列出 RabbitMQ 已有队列（Management API），并给出推荐队列名。"""
    try:
        return list_rabbitmq_queues()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.put("/minio/rabbitmq/queue")
def catalog_minio_rabbitmq_queue_update(body: MinioRabbitMQQueueUpdate):
    """保存要监听的队列名到 config/minio.yaml，并重启消费者。"""
    try:
        queue = save_rabbitmq_queue(body.queue)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    consumer = get_minio_rabbitmq_consumer()
    consumer.restart()
    return {
        "queue": queue,
        "rabbitmq": consumer.status(),
        "queues": list_rabbitmq_queues(),
    }


@router.get("/minio/rabbitmq/recent")
def catalog_minio_rabbitmq_recent(limit: int = Query(20, ge=1, le=50)):
    """查看最近合并后的上传批次（非逐条原始 MQ）。"""
    batches = list_recent_rabbitmq_events(limit)
    return {
        "consumer": get_minio_rabbitmq_consumer().status(),
        "batches": batches,
        "events": batches,
    }


@router.post("/minio/rabbitmq/peek")
def catalog_minio_rabbitmq_peek(queue: str = Query("", description="留空则用配置中的队列")):
    """窥探队列中的一条消息（默认放回，不真正消费）。"""
    try:
        return peek_rabbitmq_message(queue or None, requeue=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/minio/test-upload")
def catalog_minio_test_upload(body: MinioTestUploadRequest):
    """上传测试套图：默认经 Alist（生产路径），MinIO 存图后等待 RabbitMQ 自动通知。"""
    try:
        result = upload_test_image_set(
            family_code=body.family_code,
            image_set=body.image_set,
            product_code=body.product_code,
            category=body.category,
            image_numbers=body.image_numbers,
            upload_method=body.upload_method,
            publish_rabbitmq=body.publish_rabbitmq,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    payload = result.to_dict()
    if body.process_local and result.upload_method == "minio" and body.publish_rabbitmq:
        events = [
            MinioUploadEvent(object_key=key, bucket=result.bucket, event_name="test_upload")
            for key in result.object_keys
        ]
        payload["local_process"] = get_minio_rabbitmq_consumer().process_upload_events(events)
    payload["recent_events"] = list_recent_rabbitmq_events(5)
    payload["consumer"] = get_minio_rabbitmq_consumer().status()
    return payload


@router.post("/minio/upload-folder")
async def catalog_minio_upload_folder(
    category: str = Form(..., description="笔袋 | 公仔 | 视频"),
    folder_name: str = Form(..., description="本地文件夹名，如 BD021 / 第二套图 / BD713Z"),
    paths: list[str] = Form(..., description="与 files 一一对应的相对路径"),
    files: list[UploadFile] = File(...),
    upload_mode: str = Form("family", description="family | image_set | product"),
    target_family: str = Form("", description="追加套图/商品时的目标款号，如 BD713"),
    target_image_set: str = Form("", description="追加商品时的目标套图，如 第一套图"),
):
    """经 Alist 上传本地素材文件夹。

    - family: 整款号文件夹 → 笔袋/BD713/第一套图/商品/1.jpg
    - image_set: 在已有款号下追加套图 → 笔袋/BD713/第二套图/商品/1.jpg
    - product: 在已有套图下追加商品 → 笔袋/BD713/第一套图/BD713Z/1.jpg
    """
    if len(files) != len(paths):
        raise HTTPException(status_code=400, detail="files 与 paths 数量不一致")
    if not files:
        raise HTTPException(status_code=400, detail="请选择至少一个文件")

    mode = str(upload_mode or "family").strip().lower()
    if mode not in {"family", "image_set", "product"}:
        raise HTTPException(status_code=400, detail="upload_mode 只能是 family、image_set 或 product")

    payload_files: list[tuple[str, bytes]] = []
    for upload, rel_path in zip(files, paths, strict=True):
        data = await upload.read()
        payload_files.append((rel_path, data))

    try:
        result = upload_folder_via_alist(
            category=category,
            folder_name=folder_name,
            files=payload_files,
            upload_mode=mode,  # type: ignore[arg-type]
            target_family=target_family.strip(),
            target_image_set=target_image_set.strip(),
        )
    except FolderUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    response = result.to_dict()
    if minio_refresh_mode() == "rabbitmq" and result.object_keys:
        events = [
            MinioUploadEvent(
                object_key=str(key),
                filename=str(key).rsplit("/", 1)[-1],
            )
            for key in result.object_keys
        ]
        response["local_process"] = get_minio_rabbitmq_consumer().process_upload_events(events)
    response["recent_events"] = list_recent_rabbitmq_events(5)
    response["consumer"] = get_minio_rabbitmq_consumer().status()
    return response


@router.delete("/minio/image-set", response_model=MinioImageSetDeleteResponse)
def catalog_minio_delete_image_set(body: MinioImageSetDeleteRequest):
    """删除一套图：MinIO 对象 + Alist 目录 + Redis 索引 + 本地缓存。"""
    if not minio_configured():
        raise HTTPException(status_code=503, detail="MinIO 未配置，请填写 config/minio.yaml")
    if not body.selector and not (body.family_code and body.image_set):
        raise HTTPException(status_code=400, detail="请提供 selector 或 family_code + image_set")
    try:
        result = delete_minio_image_set(
            selector=body.selector,
            family_code=body.family_code,
            image_set=body.image_set,
            sync_alist=body.sync_alist,
            clear_local_cache=body.clear_local_cache,
        )
    except ImageSetDeleteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MinioAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return MinioImageSetDeleteResponse(**result.to_dict())


@router.delete("/minio/product-folder", response_model=MinioProductDeleteResponse)
def catalog_minio_delete_product_folder(body: MinioProductDeleteRequest):
    """删除套图下的单个商品文件夹；仅当套图/款号已空时才级联删除上级目录。"""
    if not minio_configured():
        raise HTTPException(status_code=503, detail="MinIO 未配置，请填写 config/minio.yaml")
    if not body.selector and not (body.family_code and body.image_set and body.product_code):
        raise HTTPException(
            status_code=400,
            detail="请提供 selector 或 family_code + image_set + product_code",
        )
    try:
        result = delete_minio_product_folder(
            selector=body.selector,
            family_code=body.family_code,
            image_set=body.image_set,
            product_code=body.product_code,
            sync_alist=body.sync_alist,
            clear_local_cache=body.clear_local_cache,
        )
    except ImageSetDeleteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MinioAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return MinioProductDeleteResponse(**result.to_dict())


@router.get("/minio/events")
async def catalog_minio_events():
    """SSE：RabbitMQ 模式下推送 MinIO 上传事件（前端实时刷新列表）。"""

    async def event_stream():
        async for payload in subscribe_minio_events():
            yield format_sse(payload)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    """上架前校验（不打开浏览器）；MinIO 模式仅读本地缓存，需先调用 /minio/sync。"""
    source = body.material_source if body.material_source in {"local", "minio"} else "local"
    if source == "minio" and not minio_configured():
        raise HTTPException(status_code=503, detail="MinIO 未配置，请填写 config/minio.yaml")
    return run_preflight_api(body.product_codes, material_source=source)


@router.post("/minio/sync", response_model=MinioSyncJobOut)
def catalog_minio_sync_start(body: MinioSyncStartRequest):
    """异步从 MinIO 同步素材到本地缓存，立即返回 job_id。"""
    if not minio_configured():
        raise HTTPException(status_code=503, detail="MinIO 未配置，请填写 config/minio.yaml")
    try:
        job = start_minio_sync_job(body.product_codes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return MinioSyncJobOut.model_validate(job.to_dict())


@router.get("/minio/sync/active", response_model=MinioSyncJobOut | None)
def catalog_minio_sync_active():
    """当前进行中的 MinIO 同步任务（无则 null）。"""
    job = get_active_minio_sync_job()
    if not job:
        return None
    return MinioSyncJobOut.model_validate(job.to_dict())


@router.get("/minio/sync/{job_id}", response_model=MinioSyncJobOut)
def catalog_minio_sync_status(job_id: str):
    """查询 MinIO 同步任务进度。"""
    job = get_minio_sync_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"sync job not found: {job_id}")
    return MinioSyncJobOut.model_validate(job.to_dict())
