"""向 MinIO 上传测试套图；默认经 Alist（生产路径），可选 API 直传调试。"""



from __future__ import annotations



import base64

import io

from dataclasses import dataclass

from typing import Any, Literal



from pdd_agent.core.logging import get_logger

from pdd_agent.integrations.minio.alist_client import (

    AlistAPIError,

    alist_configured,

    login_alist,

    upload_bytes_via_alist,

)

from pdd_agent.integrations.minio.client import MinioAPIError, get_minio_client

from pdd_agent.integrations.minio.config import MinioConfig, load_minio_config, minio_configured, minio_scan_prefixes

from pdd_agent.integrations.minio.rabbitmq_admin import publish_rabbitmq_upload_notifications



logger = get_logger(__name__)



UploadMethod = Literal["alist", "minio"]



_MINI_JPEG = base64.b64decode(

    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxISEhUSEhIVFhUVFRUVFRUVFRUWFxUX"

    "FhUYHSggGBolGxUVITEhJSkrLi4uFx8zODMsNygtLisBCgoKDg0OGxAQGy0lICUtLS0t"

    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLf/AABEIAAEA"

    "AQMBIgACEQEDEQH/xAAXAAEBAQEAAAAAAAAAAAAAAAAAAQID/8QAFhEBAQEAAAAAAAAA"

    "AAAAAAAAAAAB/9oADAMBAAIQAxAAAAGwP//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEA"

    "AT8Af//EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQIBAT8Af//EABQRAQAAAAAAAAAAAAAA"

    "AAAAAAD/2gAIAQMBAT8Af//Z"

)





@dataclass(frozen=True)

class TestUploadResult:

    object_keys: tuple[str, ...]

    bucket: str

    upload_method: UploadMethod

    alist_paths: tuple[str, ...] = ()

    rabbitmq_published: int = 0

    rabbitmq_queue: str = ""



    def to_dict(self) -> dict[str, Any]:

        return {

            "bucket": self.bucket,

            "object_keys": list(self.object_keys),

            "upload_count": len(self.object_keys),

            "upload_method": self.upload_method,

            "alist_paths": list(self.alist_paths),

            "rabbitmq_published": self.rabbitmq_published,

            "rabbitmq_queue": self.rabbitmq_queue,

            "selector": _selector_from_keys(self.object_keys),

            "flow": (

                "Alist -> MinIO -> RabbitMQ 自动通知"

                if self.upload_method == "alist"

                else "MinIO API 直传（不会自动进队列）"

            ),

        }





def _selector_from_keys(keys: tuple[str, ...]) -> str:

    from pdd_agent.integrations.minio.events import MinioUploadEvent



    for key in keys:

        event = MinioUploadEvent(object_key=key)

        if event.selector:

            return event.selector

    return ""





def _resolve_category(category: str, cfg: MinioConfig) -> str:

    text = str(category or "").strip()

    if text:

        return text.strip("/")

    prefixes = minio_scan_prefixes(cfg)

    if prefixes and prefixes[0]:

        return prefixes[0].strip("/")

    if cfg.categories:

        return str(cfg.categories[0]).strip().strip("/")

    return "笔袋"





def _resolve_upload_method(method: str, cfg: MinioConfig) -> UploadMethod:

    normalized = str(method or "alist").strip().lower()

    if normalized == "minio":

        return "minio"

    if alist_configured(cfg):

        return "alist"

    if normalized == "alist":

        raise AlistAPIError("Alist 未配置：请在 config/minio.yaml 填写 alist 段")

    return "minio"





def build_test_object_key(

    *,

    category: str,

    family_code: str,

    image_set: str,

    product_code: str,

    filename: str,

) -> str:

    category_text = str(category or "").strip().strip("/")

    family = str(family_code or "").strip().strip("/")

    image_set_text = str(image_set or "").strip().strip("/")

    product_folder = str(product_code or "").strip().strip("/")

    name = str(filename or "").strip().lstrip("/")

    if not all([category_text, family, image_set_text, product_folder, name]):

        raise ValueError("category/family_code/image_set/product_code/filename 均不能为空")

    return f"{category_text}/{family}/{image_set_text}/{product_folder}/{name}"





def upload_test_image_set(

    *,

    family_code: str = "BD999",

    image_set: str = "第一套图",

    product_code: str = "BD999A测试笔袋",

    category: str = "",

    image_numbers: list[int] | None = None,

    upload_method: str = "alist",

    publish_rabbitmq: bool = False,

    config: MinioConfig | None = None,

) -> TestUploadResult:

    """上传一套编号测试图。默认经 Alist，走生产通知链路。"""

    cfg = config or load_minio_config()

    method = _resolve_upload_method(upload_method, cfg)

    if method == "minio" and not minio_configured(cfg):

        raise MinioAPIError("MinIO 未配置")



    numbers = image_numbers or [1, 2, 3, 4, 5]

    cleaned_numbers: list[int] = []

    for raw in numbers:

        num = int(raw)

        if num <= 0 or num > 99:

            raise ValueError("image_numbers 需在 1-99 之间")

        if num not in cleaned_numbers:

            cleaned_numbers.append(num)

    if not cleaned_numbers:

        raise ValueError("请至少提供一个图片编号")



    category_text = _resolve_category(category, cfg)

    uploaded: list[str] = []

    alist_paths: list[str] = []



    if method == "alist":

        token = login_alist(config=cfg)

        for num in cleaned_numbers:

            key = build_test_object_key(

                category=category_text,

                family_code=family_code,

                image_set=image_set,

                product_code=product_code,

                filename=f"{num}.jpg",

            )

            result = upload_bytes_via_alist(

                key,

                _MINI_JPEG,

                token=token,

                config=cfg,

            )

            uploaded.append(key)

            alist_paths.append(result.virtual_path)

            logger.info("alist test uploaded key=%s path=%s", key, result.virtual_path)

    else:

        client = get_minio_client(cfg)

        for num in cleaned_numbers:

            key = build_test_object_key(

                category=category_text,

                family_code=family_code,

                image_set=image_set,

                product_code=product_code,

                filename=f"{num}.jpg",

            )

            data = _MINI_JPEG

            client.put_object(

                cfg.bucket,

                key,

                io.BytesIO(data),

                length=len(data),

                content_type="image/jpeg",

            )

            uploaded.append(key)

            logger.info("minio test uploaded key=%s", key)



    published = 0

    queue = cfg.rabbitmq.queue

    if method == "minio" and publish_rabbitmq and queue:

        published = publish_rabbitmq_upload_notifications(uploaded, bucket=cfg.bucket, config=cfg)



    return TestUploadResult(

        object_keys=tuple(uploaded),

        bucket=cfg.bucket,

        upload_method=method,

        alist_paths=tuple(alist_paths),

        rabbitmq_published=published,

        rabbitmq_queue=queue if published else "",

    )


