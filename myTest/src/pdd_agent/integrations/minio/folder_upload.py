"""经 Alist 上传本地文件夹到 MinIO（保留目录结构）。"""



from __future__ import annotations



from dataclasses import dataclass

from pathlib import Path

from typing import Any, Literal



from pdd_agent.core.logging import get_logger

from pdd_agent.integrations.minio.alist_client import (

    AlistAPIError,

    alist_configured,

    login_alist,

    upload_bytes_via_alist,

)

from pdd_agent.integrations.minio.config import MinioConfig, load_minio_config

from pdd_agent.skills.listing.catalog import IMAGE_EXTS



logger = get_logger(__name__)



UPLOAD_CATEGORIES = ("笔袋", "公仔", "视频")

UploadMode = Literal["family", "image_set", "product"]





class FolderUploadError(ValueError):

    pass





@dataclass(frozen=True)

class FolderUploadResult:

    category: str

    folder_name: str

    object_keys: tuple[str, ...]

    skipped: tuple[str, ...]

    bucket: str

    upload_method: str = "alist"



    def to_dict(self) -> dict[str, Any]:

        return {

            "category": self.category,

            "folder_name": self.folder_name,

            "bucket": self.bucket,

            "upload_count": len(self.object_keys),

            "object_keys": list(self.object_keys),

            "skipped": list(self.skipped),

            "upload_method": self.upload_method,

            "flow": "Alist -> MinIO -> RabbitMQ 自动通知",

        }





def normalize_relative_path(raw: str) -> str:

    text = str(raw or "").replace("\\", "/").strip().lstrip("/")

    parts = [part for part in text.split("/") if part and part not in {".", ".."}]

    return "/".join(parts)





def build_folder_object_key(

    *,

    category: str,

    folder_name: str,

    relative_path: str,

) -> str:

    category_text = str(category or "").strip().strip("/")

    folder = str(folder_name or "").strip().strip("/")

    rel = normalize_relative_path(relative_path)

    if not category_text or not folder or not rel:

        raise FolderUploadError("category、folder_name、relative_path 均不能为空")

    if rel.split("/", 1)[0] == folder:

        return f"{category_text}/{rel}"

    return f"{category_text}/{folder}/{rel}"


def build_material_object_key(
    *,
    category: str,
    upload_mode: UploadMode = "family",
    folder_name: str,
    relative_path: str,
    target_family: str = "",
    target_image_set: str = "",
) -> str:
    """构建 MinIO object key。

    family: 笔袋/BD713/第一套图/商品/1.jpg（选整个款号文件夹）
    image_set: 笔袋/BD713/第二套图/商品/1.jpg（在已有款号下追加套图文件夹）
    product: 笔袋/BD713/第一套图/BD713Z/1.jpg（在已有套图下追加商品文件夹）
    """
    if upload_mode == "family":
        return build_folder_object_key(
            category=category,
            folder_name=folder_name,
            relative_path=relative_path,
        )

    category_text = str(category or "").strip().strip("/")
    family = str(target_family or "").strip().strip("/")
    folder = str(folder_name or "").strip().strip("/")
    rel = normalize_relative_path(relative_path)

    if not family:
        raise FolderUploadError("追加套图/商品时需填写目标款号")

    if upload_mode == "image_set":
        image_set = folder
        if not image_set:
            raise FolderUploadError("套图文件夹名不能为空")
        prefix = f"{category_text}/{family}/{image_set}"
        return f"{prefix}/{rel}" if rel else prefix

    if upload_mode == "product":
        image_set = str(target_image_set or "").strip().strip("/")
        product_folder = folder
        if not image_set:
            raise FolderUploadError("追加商品时需选择目标套图")
        if not product_folder:
            raise FolderUploadError("商品文件夹名不能为空")
        if rel.startswith(f"{product_folder}/"):
            rel = rel.split("/", 1)[1]
        elif rel == product_folder:
            raise FolderUploadError("请选择商品文件夹内的图片，而不是文件夹本身")
        prefix = f"{category_text}/{family}/{image_set}/{product_folder}"
        return f"{prefix}/{rel}" if rel else prefix

    raise FolderUploadError(f"不支持的上传模式: {upload_mode}")





def is_uploadable_image(relative_path: str) -> bool:

    rel = normalize_relative_path(relative_path)

    if not rel:

        return False

    if any(part.startswith(".") for part in rel.split("/")):

        return False

    if "/.alist" in f"/{rel}/":

        return False

    return Path(rel).suffix.lower() in IMAGE_EXTS





def upload_folder_via_alist(

    *,

    category: str,

    folder_name: str,

    files: list[tuple[str, bytes]],

    config: MinioConfig | None = None,

    upload_mode: UploadMode = "family",

    target_family: str = "",

    target_image_set: str = "",

) -> FolderUploadResult:

    """经 Alist 上传本地素材；upload_mode 支持 family / image_set / product。"""

    return upload_material_via_alist(

        category=category,

        upload_mode=upload_mode,

        folder_name=folder_name,

        target_family=target_family,

        target_image_set=target_image_set,

        files=files,

        config=config,

    )


def upload_material_via_alist(

    *,

    category: str,

    upload_mode: UploadMode = "family",

    folder_name: str,

    target_family: str = "",

    target_image_set: str = "",

    files: list[tuple[str, bytes]],

    config: MinioConfig | None = None,

) -> FolderUploadResult:

    """files: [(relative_path, content), ...]"""

    cfg = config or load_minio_config()

    if not alist_configured(cfg):

        raise AlistAPIError("Alist 未配置")



    category_text = str(category or "").strip().strip("/")

    if category_text not in UPLOAD_CATEGORIES:

        raise FolderUploadError(f"类目只能是：{' / '.join(UPLOAD_CATEGORIES)}")



    folder = str(folder_name or "").strip().strip("/")

    if not folder:

        raise FolderUploadError("folder_name 不能为空")



    uploaded: list[str] = []

    skipped: list[str] = []

    token = login_alist(config=cfg)



    for relative_path, data in files:

        rel = normalize_relative_path(relative_path)

        if not rel:

            continue

        if not is_uploadable_image(rel):

            skipped.append(rel)

            continue

        if not data:

            skipped.append(rel)

            continue



        object_key = build_material_object_key(

            category=category_text,

            upload_mode=upload_mode,

            folder_name=folder,

            relative_path=rel,

            target_family=target_family,

            target_image_set=target_image_set,

        )

        content_type = _content_type_for_path(rel)

        upload_bytes_via_alist(object_key, data, content_type=content_type, token=token, config=cfg)

        uploaded.append(object_key)

        logger.info("material upload key=%s bytes=%s mode=%s", object_key, len(data), upload_mode)



    if not uploaded:

        raise FolderUploadError("没有可上传的图片文件（支持 jpg/png/webp 等）")



    return FolderUploadResult(

        category=category_text,

        folder_name=folder,

        object_keys=tuple(uploaded),

        skipped=tuple(skipped),

        bucket=cfg.bucket,

    )





def _content_type_for_path(relative_path: str) -> str:

    suffix = Path(relative_path).suffix.lower()

    mapping = {

        ".jpg": "image/jpeg",

        ".jpeg": "image/jpeg",

        ".png": "image/png",

        ".webp": "image/webp",

        ".gif": "image/gif",

    }

    return mapping.get(suffix, "application/octet-stream")


