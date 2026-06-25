"""
整合链路 — 已上架商品重复上架处理策略（独立模块）。

策略：
- ignore：保持现有行为（跳过上架 / 部分跳过等，由前端 resolveListingIntent 决定）
- append_to_existing：占位，尚未实现
- delist_and_relist：先精准下架拼多多在售商品，再删除本地已发布记录，然后重新上架
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pdd_agent.api.services.task_runner import create_delist_run
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import (
    delete_published_product,
    enqueue_task,
    get_integrated_pipeline,
    get_published_product,
    update_integrated_pipeline,
)
from pdd_agent.domain.enums import AgentKind

logger = get_logger(__name__)

RelistStrategy = Literal["ignore", "append_to_existing", "delist_and_relist"]

RELIST_STRATEGY_VALUES: frozenset[str] = frozenset({"ignore", "append_to_existing", "delist_and_relist"})

RELIST_STRATEGY_LABELS: dict[str, str] = {
    "ignore": "不管（沿用当前跳过上架/重新上架提示）",
    "append_to_existing": "原 ID 链接补漏（开发中）",
    "delist_and_relist": "下架原商品并重新上架",
}


def normalize_relist_strategy(value: str | None) -> RelistStrategy:
    text = str(value or "ignore").strip()
    if text in RELIST_STRATEGY_VALUES:
        return text  # type: ignore[return-value]
    return "ignore"


def validate_relist_strategy_for_start(strategy: RelistStrategy) -> None:
    if strategy == "append_to_existing":
        raise ValueError("「原 ID 链接补漏」功能尚未实现，请选择其他策略或稍后再试")


def resolve_listing_flags_for_strategy(
    strategy: RelistStrategy,
    *,
    skip_listing: bool,
    listing_skip_selectors: list[str] | None,
) -> tuple[bool, list[str]]:
    """根据策略调整 skip_listing / listing_skip_selectors。"""
    if strategy == "delist_and_relist":
        return False, []
    return bool(skip_listing), list(listing_skip_selectors or [])


@dataclass(frozen=True)
class RelistPrepTarget:
    selector: str
    mapping_id: str
    pdd_product_id: str
    merchant_code: str


def _parse_selector(selector: str) -> tuple[str, str, str]:
    parts = [part.strip() for part in str(selector or "").split("/") if part.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[-1]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    if len(parts) == 1:
        return "", "", parts[0]
    return "", "", ""


def collect_on_sale_relist_targets(
    account_id: str,
    selectors: list[str],
) -> list[RelistPrepTarget]:
    """为每个 selector 生成下架预备目标（含商品编码；重复上架时会在浏览器侧扫全在售 ID）。"""
    account_id = str(account_id or "").strip()
    targets: list[RelistPrepTarget] = []
    seen_merchant: set[str] = set()
    for selector in selectors:
        selector = str(selector or "").strip()
        if not selector:
            continue
        _family, image_set, product_code = _parse_selector(selector)
        if not product_code:
            continue
        merchant_key = product_code.casefold()
        if merchant_key in seen_merchant:
            continue
        seen_merchant.add(merchant_key)

        row = get_published_product(
            account_id=account_id,
            product_code=product_code,
            image_set=image_set,
        )
        mapping_id = ""
        pdd_product_id = ""
        if row and str(row.status or "") == "on_sale":
            mapping_id = str(row.mapping_id or "").strip()
            pdd_product_id = str(row.pdd_product_id or "").strip()

        targets.append(
            RelistPrepTarget(
                selector=selector,
                mapping_id=mapping_id,
                pdd_product_id=pdd_product_id,
                merchant_code=product_code,
            )
        )
    return targets


@dataclass
class PipelineListingPlan:
    action: Literal["skip_all", "skip_partial", "listing", "relist_prep"]
    listing_codes: list[str] = field(default_factory=list)
    skip_selectors: list[str] = field(default_factory=list)
    relist_targets: list[RelistPrepTarget] = field(default_factory=list)
    pending_listing: dict[str, Any] = field(default_factory=dict)


def build_pipeline_listing_plan(
    *,
    relist_strategy: RelistStrategy,
    account_id: str,
    selectors: list[str],
    skip_listing: bool,
    skip_selectors: list[str],
    listing_payload_base: dict[str, Any],
) -> PipelineListingPlan:
    """
    决定整合链路上架阶段如何启动。

    listing_payload_base 需含 category_keyword、platform_listing_code、slot_alignment_test、material_source 等。
    """
    codes = list(dict.fromkeys(str(s).strip() for s in selectors if str(s).strip()))
    skip_set = set(skip_selectors)
    list_codes = [c for c in codes if c not in skip_set]

    if skip_listing:
        return PipelineListingPlan(action="skip_all", listing_codes=codes, skip_selectors=codes)

    if skip_selectors and not list_codes:
        return PipelineListingPlan(action="skip_all", listing_codes=[], skip_selectors=skip_selectors)

    if skip_selectors:
        return PipelineListingPlan(
            action="skip_partial",
            listing_codes=list_codes,
            skip_selectors=skip_selectors,
        )

    if relist_strategy == "delist_and_relist":
        targets = collect_on_sale_relist_targets(account_id, codes)
        if targets:
            pending = {
                **listing_payload_base,
                "product_codes": codes,
            }
            return PipelineListingPlan(
                action="relist_prep",
                listing_codes=codes,
                relist_targets=targets,
                pending_listing=pending,
            )

    return PipelineListingPlan(action="listing", listing_codes=codes)


def build_relist_prep_delist_params(targets: list[RelistPrepTarget]) -> dict[str, Any]:
    return {
        "mode": "pipeline_relist_prep",
        "dry_run": False,
        "targets": [
            {
                "selector": t.selector,
                "mapping_id": t.mapping_id,
                "target_product_id": t.pdd_product_id,
                "merchant_code": t.merchant_code,
            }
            for t in targets
        ],
    }


def enqueue_pipeline_relist_prep(
    *,
    pipeline_id: str,
    account_id: str,
    targets: list[RelistPrepTarget],
    pending_listing: dict[str, Any],
) -> str:
    """入队下架预备任务，并在 pipeline meta 中保存待上架参数。"""
    delist_run_id = create_delist_run(account_id)
    update_integrated_pipeline(
        pipeline_id,
        current_step="relist_prep_queued",
        meta_patch={
            "relist_strategy": "delist_and_relist",
            "relist_prep_run_id": delist_run_id,
            "pending_listing": pending_listing,
            "relist_prep_targets": [
                {
                    "selector": t.selector,
                    "mapping_id": t.mapping_id,
                    "pdd_product_id": t.pdd_product_id,
                    "merchant_code": t.merchant_code,
                }
                for t in targets
            ],
        },
    )
    enqueue_task(
        agent=AgentKind.DELIST.value,
        run_id=delist_run_id,
        account_id=account_id,
        payload={
            "pipeline_id": pipeline_id,
            "delist_params": build_relist_prep_delist_params(targets),
        },
        scheduled_at=datetime.now(),
    )
    logger.info(
        "pipeline relist prep queued pipeline_id=%s run_id=%s targets=%s",
        pipeline_id,
        delist_run_id,
        len(targets),
    )
    return delist_run_id


def finalize_relist_prep_after_delist(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    """
    下架预备完成后：删除已成功下架（或平台已不在售）的本地已发布记录。

    同一 mapping 可能对应多个拼多多 ID（重复上架），只删一次 DB 记录。
    返回 (deleted_mapping_ids, errors)。
    """
    deleted: list[str] = []
    errors: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}

    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        mapping_id = str(item.get("mapping_id") or "").strip()
        if mapping_id:
            grouped.setdefault(mapping_id, []).append(item)
            continue
        err = str(item.get("error") or "").strip()
        if err and err not in {"", "product_id_not_found_on_sale"}:
            selector = str(item.get("selector") or item.get("merchant_code") or "")
            errors.append(f"{selector}: {err}" if selector else err)

    for mapping_id, items in grouped.items():
        blocking = [
            str(item.get("error") or "").strip()
            for item in items
            if str(item.get("error") or "").strip()
            not in {"", "product_id_not_found_on_sale"}
            and item.get("status") != "delisted"
        ]
        if blocking:
            selector = str(items[0].get("selector") or mapping_id)
            errors.append(f"{selector}: {blocking[0]}")
            continue

        should_delete = any(
            item.get("status") == "delisted"
            or str(item.get("error") or "").strip() == "product_id_not_found_on_sale"
            for item in items
        )
        if not should_delete:
            continue
        if delete_published_product(mapping_id):
            deleted.append(mapping_id)
        else:
            errors.append(f"删除已发布记录失败: {mapping_id}")

    return deleted, errors


def enqueue_pending_listing_after_relist_prep(row) -> None:
    """下架预备成功后，启动整合链路上架任务。"""
    from pdd_agent.api.services.pipeline_listing_throttle import (
        apply_throttle_to_listing_codes,
        enqueue_listing_batch_for_pipeline,
    )

    meta = dict(row.meta or {})
    pending = dict(meta.get("pending_listing") or {})
    all_codes = list(pending.get("product_codes") or row.product_codes or [])
    if not all_codes:
        raise ValueError("relist prep 完成但缺少待上架商品列表")

    throttle = dict(meta.get("listing_throttle") or {})
    listing_payload_base = dict(throttle.get("listing_payload_base") or pending)
    batch_codes = apply_throttle_to_listing_codes(all_codes, throttle if throttle.get("enabled") else None)

    update_integrated_pipeline(
        row.pipeline_id,
        current_step="listing_queued",
        meta_patch={
            "relist_prep_completed_at": datetime.now().isoformat(timespec="seconds"),
        },
    )

    if throttle.get("enabled"):
        enqueue_listing_batch_for_pipeline(
            pipeline_id=row.pipeline_id,
            account_id=row.account_id,
            batch_codes=batch_codes,
            listing_payload_base=listing_payload_base,
        )
    else:
        listing_run_id = str(row.listing_run_id or "").strip()
        if not listing_run_id:
            raise ValueError("relist prep 完成但缺少 listing_run_id")
        enqueue_task(
            agent=AgentKind.LISTING.value,
            run_id=listing_run_id,
            account_id=row.account_id,
            payload={
                "product_codes": batch_codes,
                "dry_run": False,
                "category_keyword": str(listing_payload_base.get("category_keyword") or "玩偶"),
                "platform_listing_code": str(listing_payload_base.get("platform_listing_code") or ""),
                "pipeline_id": row.pipeline_id,
                "slot_alignment_test": bool(listing_payload_base.get("slot_alignment_test")),
                "material_source": str(listing_payload_base.get("material_source") or ""),
            },
            scheduled_at=datetime.now(),
        )
    logger.info(
        "pipeline listing enqueued after relist prep pipeline_id=%s products=%s throttle=%s",
        row.pipeline_id,
        len(batch_codes),
        bool(throttle.get("enabled")),
    )


def handle_pipeline_delist_task_finished(
    *,
    pipeline_id: str,
    run_id: str = "",
    success: bool,
    result: dict[str, Any] | None,
    error: str = "",
) -> bool:
    """
    整合链路 DELIST 任务结束回调。若为本模块触发的 relist prep，则处理并可能入队上架。

    返回 True 表示已消费该事件；False 表示与普通下架任务无关。
    """
    pipeline_id = str(pipeline_id or "").strip()
    if not pipeline_id:
        return False
    row = get_integrated_pipeline(pipeline_id)
    if not row:
        return False
    meta = dict(row.meta or {})
    if normalize_relist_strategy(meta.get("relist_strategy")) != "delist_and_relist":
        return False
    if not meta.get("pending_listing"):
        return False
    prep_run_id = str(meta.get("relist_prep_run_id") or "").strip()
    if prep_run_id and run_id and prep_run_id != str(run_id).strip():
        return False

    result = result if isinstance(result, dict) else {}

    if not success:
        err = error or "下架预备失败"
        update_integrated_pipeline(
            pipeline_id,
            status="failed",
            current_step="relist_prep_failed",
            error=err,
        )
        return True

    if result.get("delist_skipped"):
        skip_reason = str(result.get("skip_reason") or "verification_failed")
        warnings = list(result.get("warnings") or [])
        warning_text = warnings[0] if warnings else "下架校验未通过，已跳过下架"
        update_integrated_pipeline(
            pipeline_id,
            meta_patch={
                "relist_prep_skipped": True,
                "relist_prep_skip_reason": skip_reason,
                "relist_prep_skip_message": warning_text,
            },
        )
        try:
            refreshed = get_integrated_pipeline(pipeline_id) or row
            enqueue_pending_listing_after_relist_prep(refreshed)
        except Exception as exc:
            update_integrated_pipeline(
                pipeline_id,
                status="failed",
                current_step="relist_prep_failed",
                error=str(exc),
            )
        return True

    deleted, finalize_errors = finalize_relist_prep_after_delist(result)
    if finalize_errors:
        err = "；".join(finalize_errors)
        update_integrated_pipeline(
            pipeline_id,
            status="failed",
            current_step="relist_prep_failed",
            error=err,
            meta_patch={"relist_prep_deleted_mapping_ids": deleted},
        )
        return True

    update_integrated_pipeline(
        pipeline_id,
        meta_patch={"relist_prep_deleted_mapping_ids": deleted},
    )
    try:
        refreshed = get_integrated_pipeline(pipeline_id) or row
        enqueue_pending_listing_after_relist_prep(refreshed)
    except Exception as exc:
        update_integrated_pipeline(
            pipeline_id,
            status="failed",
            current_step="relist_prep_failed",
            error=str(exc),
        )
    return True


def append_to_existing_placeholder(*_args, **_kwargs) -> None:
    """占位：原 ID 链接补漏，尚未实现。"""
    raise NotImplementedError("append_to_existing strategy is not implemented yet")
