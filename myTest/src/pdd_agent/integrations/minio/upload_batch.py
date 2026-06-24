"""将多条单文件 MQ 消息合并为可读的「上传批次」摘要。"""



from __future__ import annotations



from collections import defaultdict

from dataclasses import dataclass

from typing import Any, Literal



from pdd_agent.integrations.minio.config import MinioConfig, load_minio_config

from pdd_agent.integrations.minio.events import MinioUploadEvent

from pdd_agent.integrations.minio.folder_upload import UPLOAD_CATEGORIES

from pdd_agent.integrations.minio.index import load_set_index_record



UploadChangeType = Literal[

    "new_product_folder",

    "append_to_product",

    "new_image_set",

    "unrecognized",

]



CHANGE_LABELS: dict[str, str] = {

    "new_product_folder": "新增商品文件夹",

    "append_to_product": "追加图片",

    "new_image_set": "新增套图",

    "unrecognized": "未识别",

}





@dataclass(frozen=True)

class UploadProductGroup:

    change_type: UploadChangeType

    category: str

    family_code: str

    image_set: str

    product_code: str

    product_folder: str

    files: tuple[str, ...]



    @property

    def selector(self) -> str:

        return f"{self.family_code}/{self.image_set}"



    @property

    def folder_path(self) -> str:

        parts = [self.category, self.family_code, self.image_set, self.product_folder]

        return "/".join(part for part in parts if part)



    @property

    def change_label(self) -> str:

        return CHANGE_LABELS.get(self.change_type, self.change_type)



    def to_dict(self) -> dict[str, Any]:

        return {

            "change_type": self.change_type,

            "change_label": self.change_label,

            "category": self.category,

            "path": self.folder_path,

            "selector": self.selector,

            "product_code": self.product_code,

            "product_folder": self.product_folder,

            "file_count": len(self.files),

            "files": list(self.files),

        }





def _category_from_key(object_key: str, cfg: MinioConfig) -> str:

    parts = [part for part in str(object_key or "").split("/") if part]

    if not parts:

        return ""

    first = parts[0]

    allowed = set(cfg.categories) | set(UPLOAD_CATEGORIES)

    return first if first in allowed else ""





def _classify_product_change(

    cfg: MinioConfig,

    *,

    family_code: str,

    image_set: str,

    product_code: str,

) -> UploadChangeType:

    selector = f"{family_code}/{image_set}"

    record = load_set_index_record(cfg, selector)

    if record is None:

        return "new_image_set"

    if product_code not in record.product_codes:

        return "new_product_folder"

    return "append_to_product"


def snapshot_set_product_codes(
    events: list[MinioUploadEvent],
    *,
    config: MinioConfig | None = None,
) -> dict[str, set[str] | None]:
    """上传批次处理前，记录各套图已有商品编码；None 表示索引中尚无该套图。"""
    cfg = config or load_minio_config()
    snapshot: dict[str, set[str] | None] = {}
    for event in events:
        parsed = event._parsed()
        if not parsed:
            continue
        family_code, image_set, product_code = parsed
        selector = f"{family_code}/{image_set}"
        if selector in snapshot:
            continue
        record = load_set_index_record(cfg, selector)
        snapshot[selector] = set(record.product_codes) if record else None
    return snapshot


def classify_change_from_snapshot(
    *,
    selector: str,
    product_code: str,
    snapshot: dict[str, set[str] | None],
) -> UploadChangeType:
    prior = snapshot.get(selector)
    if prior is None:
        return "new_image_set"
    if product_code not in prior:
        return "new_product_folder"
    return "append_to_product"


def apply_snapshot_to_batch_summary(
    batch_summary: dict[str, Any],
    snapshot: dict[str, set[str] | None],
) -> None:
    """按上传前的索引快照重算 change_type，并刷新 summary 文案。"""
    groups_raw = batch_summary.get("groups") or []
    if not isinstance(groups_raw, list):
        return
    for group in groups_raw:
        if not isinstance(group, dict):
            continue
        selector = str(group.get("selector") or "").strip()
        product_code = str(group.get("product_code") or "").strip()
        if not selector or not product_code:
            continue
        change_type = classify_change_from_snapshot(
            selector=selector,
            product_code=product_code,
            snapshot=snapshot,
        )
        group["change_type"] = change_type
        group["change_label"] = CHANGE_LABELS.get(change_type, change_type)

    content_parts = [
        f"{group.get('change_label') or group.get('change_type')}：{group.get('path')}（{group.get('file_count', 0)} 张）"
        for group in groups_raw
        if isinstance(group, dict) and group.get("path")
    ]
    if content_parts and batch_summary.get("status") in {"success", "partial"}:
        summary = f"上传成功：{'；'.join(content_parts)}"
        ignored = int(batch_summary.get("ignored_system_count") or 0)
        if ignored:
            summary += f"（另有 {ignored} 条 Alist/系统通知已忽略，可无视）"
        batch_summary["summary"] = summary
        batch_summary["detail"] = "；".join(
            f"{group.get('change_label')} {group.get('selector')}（{group.get('product_code')}）"
            for group in groups_raw
            if isinstance(group, dict) and group.get("selector")
        )


def batch_introduces_new_products(batch_summary: dict[str, Any]) -> bool:
    allowed = frozenset({"new_image_set", "new_product_folder"})
    for group in batch_summary.get("groups") or []:
        if isinstance(group, dict) and str(group.get("change_type") or "") in allowed:
            return True
    return False


def prepare_upload_batch(
    events: list[MinioUploadEvent],
    *,
    raw_message_count: int = 0,
    config: MinioConfig | None = None,
) -> tuple[dict[str, Any], dict[str, set[str] | None]]:
    """构建批次摘要，并按「处理前索引」校正分类（避免重复 MQ 通知误判为追加）。"""
    cfg = config or load_minio_config()
    snapshot = snapshot_set_product_codes(events, config=cfg)
    batch_summary = build_upload_batch_summary(
        events,
        raw_message_count=raw_message_count,
        config=cfg,
    )
    apply_snapshot_to_batch_summary(batch_summary, snapshot)
    return batch_summary, snapshot


def _is_system_notification(filename: str, object_key: str = "") -> bool:

    name = str(filename or "").strip()

    key = str(object_key or "").strip()

    if name.startswith(".") or "/." in key:

        return True

    lowered = name.lower()

    if lowered in {".alist", "alist"} or lowered.endswith(".alist"):

        return True

    if "/.alist" in key.lower():

        return True

    return False





def build_upload_batch_summary(

    events: list[MinioUploadEvent],

    *,

    raw_message_count: int = 0,

    config: MinioConfig | None = None,

) -> dict[str, Any]:

    """合并 settle 窗口内多条单文件消息为一条批次说明。"""

    cfg = config or load_minio_config()

    grouped: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)

    ignored_system_files: list[str] = []

    unrecognized_files: list[str] = []



    seen_keys: set[str] = set()

    for event in events:

        if event.object_key in seen_keys:

            continue

        seen_keys.add(event.object_key)

        filename = event.filename or event.object_key.rsplit("/", 1)[-1]

        parsed = event._parsed()

        if not parsed:

            if _is_system_notification(filename, event.object_key):

                ignored_system_files.append(filename)

            elif filename:

                unrecognized_files.append(filename)

            continue



        family_code, image_set, product_folder = parsed

        product_code = event.product_code or product_folder

        category = _category_from_key(event.object_key, cfg)

        group_key = (category, family_code, image_set, product_folder)

        grouped[group_key].append(filename)



    groups: list[UploadProductGroup] = []

    for (category, family_code, image_set, product_folder), files in sorted(grouped.items()):

        product_code = product_folder

        change_type = _classify_product_change(

            cfg,

            family_code=family_code,

            image_set=image_set,

            product_code=product_code,

        )

        groups.append(

            UploadProductGroup(

                change_type=change_type,

                category=category,

                family_code=family_code,

                image_set=image_set,

                product_code=product_code,

                product_folder=product_folder,

                files=tuple(sorted(set(files))),

            )

        )



    matched_file_count = sum(len(group.files) for group in groups)

    content_parts = [f"{group.change_label}：{group.folder_path}（{len(group.files)} 张）" for group in groups]



    if matched_file_count > 0:

        status = "success"

        summary = f"上传成功：{'；'.join(content_parts)}"

        if ignored_system_files:

            summary += f"（另有 {len(ignored_system_files)} 条 Alist/系统通知已忽略，可无视）"

    elif not content_parts and not unrecognized_files:

        status = "empty"

        summary = f"收到 {raw_message_count or len(events)} 条 MQ 消息，但没有有效图片"

    else:

        status = "partial"

        summary = "；".join(content_parts) if content_parts else ""

        if unrecognized_files:

            extra = f"未能识别 {len(unrecognized_files)} 张"

            summary = f"{summary}；{extra}" if summary else extra

        if ignored_system_files:

            extra = f"已忽略 {len(ignored_system_files)} 条系统通知"

            summary = f"{summary}；{extra}" if summary else extra

        if not summary:

            summary = f"收到 {raw_message_count or len(events)} 条 MQ 消息，但未能解析出套图路径"



    detail_parts = [f"{group.change_label} {group.selector}（{group.product_code}）" for group in groups]



    return {

        "kind": "upload_batch",

        "status": status,

        "summary": summary,

        "detail": "；".join(detail_parts) if detail_parts else summary,

        "raw_message_count": raw_message_count or len(events),

        "matched_file_count": matched_file_count,

        "ignored_system_count": len(ignored_system_files),

        "unrecognized_file_count": len(unrecognized_files),

        "ignored_system_files": ignored_system_files[:20],

        "unrecognized_files": unrecognized_files[:20],

        "groups": [group.to_dict() for group in groups],

        "selectors": sorted({group.selector for group in groups}),

        "product_codes": sorted({group.product_code for group in groups}),

    }


