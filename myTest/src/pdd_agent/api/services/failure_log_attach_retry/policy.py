"""
失败日志挂回原链路重跑。

开关开启且候选带 source_pipeline_id 时：
  占用失败日志 → 在原链路补上架 → 上架成功进限时 → 精准回写每批商品状态
  → 限时成功合并活动池并改期活动（与分批限时重跑同类）。

不再 start_integrated_pipeline 新建链路。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pdd_agent.api.services.failure_log_attach_retry.constants import (
    ACTIVE_PHASES,
    META_STATE_KEY,
    PAYLOAD_FLAG,
    PHASE_DONE,
    PHASE_FAILED,
    PHASE_IDLE,
    PHASE_LIMITED_TIME,
    PHASE_LISTING,
    PHASE_PARTIAL,
)
from pdd_agent.api.services.task_runner import create_campaign_run, create_listing_run
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import (
    enqueue_task,
    get_integrated_pipeline,
    update_integrated_pipeline,
)
from pdd_agent.domain.enums import AgentKind, RunStatus
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)


def _meta(row) -> dict[str, Any]:
    raw = getattr(row, "meta", None) if row is not None else None
    return dict(raw) if isinstance(raw, dict) else {}


def _merge_unique(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def attach_retry_state(row) -> dict[str, Any]:
    state = _meta(row).get(META_STATE_KEY)
    return dict(state) if isinstance(state, dict) else {}


def _save_state(row, patch: dict[str, Any]) -> None:
    current = attach_retry_state(row)
    current.update(patch)
    update_integrated_pipeline(row.pipeline_id, meta_patch={META_STATE_KEY: current})
    meta = _meta(row)
    meta[META_STATE_KEY] = current
    try:
        row.meta = meta
    except Exception:
        pass


def is_attach_retry_listing_run(row, run_id: str) -> bool:
    rid = str(run_id or "").strip()
    if not rid:
        return False
    state = attach_retry_state(row)
    return str(state.get("listing_run_id") or "").strip() == rid


def is_attach_retry_limited_time_run(row, run_id: str) -> bool:
    rid = str(run_id or "").strip()
    if not rid:
        return False
    state = attach_retry_state(row)
    return str(state.get("limited_time_run_id") or "").strip() == rid


def build_attach_retry_public_state(row) -> dict[str, Any]:
    from pdd_agent.api.services.failure_log_attach_retry.activity_policy import (
        build_attach_retry_activity_public_state,
    )

    state = attach_retry_state(row)
    return {
        "phase": str(state.get("phase") or PHASE_IDLE),
        "feishu_record_id": str(state.get("feishu_record_id") or ""),
        "merchant_code": str(state.get("merchant_code") or ""),
        "selectors": list(state.get("selectors") or []),
        "batch_indices": list(state.get("batch_indices") or []),
        "listing_run_id": str(state.get("listing_run_id") or ""),
        "limited_time_run_id": str(state.get("limited_time_run_id") or ""),
        "outcome": str(state.get("outcome") or ""),
        "outcome_detail": str(state.get("outcome_detail") or ""),
        "activity_defer": build_attach_retry_activity_public_state(row),
    }


def _listing_payload_base(row) -> dict[str, Any]:
    from pdd_agent.api.services.pipeline_late_retry_policy import _listing_payload_base as _base

    return _base(row)


def _patch_targets_listing_success(
    *,
    pipeline_id: str,
    targets: list[dict[str, Any]],
    result: dict[str, Any],
) -> tuple[list[str], list[str]]:
    from pdd_agent.api.services.failure_log_attach_retry.stage_patch import patch_batch_product_stage
    from pdd_agent.api.services.pipeline_batch_product_stage_tracker import STAGE_FAILED, STAGE_SUCCESS
    from pdd_agent.api.services.pipeline_service import _extract_listing_products, _selector_to_listing_label

    pdd_ids, mapping_ids = _extract_listing_products(result)
    results_by_label: dict[str, dict[str, Any]] = {}
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("listing_label") or "").strip()
        if label:
            results_by_label[label] = item

    succeeded_pdd: list[str] = []
    succeeded_map: list[str] = []
    for target in targets:
        selector = str(target.get("product_selector") or "").strip()
        batch_index = target.get("batch_index")
        label = _selector_to_listing_label(selector) if selector else ""
        item = results_by_label.get(label) or results_by_label.get(selector)
        status = str((item or {}).get("status") or "").strip().lower()
        product_id = str((item or {}).get("pdd_product_id") or "").strip()
        mapping_id = str((item or {}).get("mapping_id") or "").strip()
        ok = status in {"success", "listed"} and bool(product_id or status == "listed")
        if not ok and pdd_ids and len(targets) == 1:
            # 单目标时允许用整单提取结果兜底
            product_id = product_id or (pdd_ids[0] if pdd_ids else "")
            mapping_id = mapping_id or (mapping_ids[0] if mapping_ids else "")
            ok = bool(product_id)
        if ok:
            succeeded_pdd.append(product_id)
            if mapping_id:
                succeeded_map.append(mapping_id)
            if selector or product_id:
                try:
                    patch_batch_product_stage(
                        pipeline_id=pipeline_id,
                        batch_index=int(batch_index) if batch_index is not None else None,
                        product_selector=selector,
                        pdd_product_id=str(target.get("pdd_product_id") or ""),
                        listing_status=STAGE_SUCCESS,
                        listing_error="",
                        set_pdd_product_id=product_id,
                        set_mapping_id=mapping_id,
                    )
                except Exception:
                    logger.exception(
                        "attach retry patch listing success failed pipeline=%s selector=%s",
                        pipeline_id,
                        selector,
                    )
        elif selector or target.get("pdd_product_id"):
            try:
                patch_batch_product_stage(
                    pipeline_id=pipeline_id,
                    batch_index=int(batch_index) if batch_index is not None else None,
                    product_selector=selector,
                    pdd_product_id=str(target.get("pdd_product_id") or ""),
                    listing_status=STAGE_FAILED,
                    listing_error=str((item or {}).get("error") or "挂回原链路上架失败"),
                )
            except Exception:
                logger.exception(
                    "attach retry patch listing failed pipeline=%s selector=%s",
                    pipeline_id,
                    selector,
                )

    if not succeeded_pdd:
        succeeded_pdd = list(pdd_ids)
        succeeded_map = list(mapping_ids)
    return _merge_unique(succeeded_pdd), _merge_unique(succeeded_map)


def _patch_targets_limited_time(
    *,
    pipeline_id: str,
    targets: list[dict[str, Any]],
    success_pdd_ids: list[str],
    failed_pdd_ids: list[str],
    error: str = "",
) -> None:
    from pdd_agent.api.services.failure_log_attach_retry.stage_patch import patch_batch_product_stage
    from pdd_agent.api.services.pipeline_batch_product_stage_tracker import STAGE_FAILED, STAGE_SUCCESS

    success_set = set(success_pdd_ids)
    failed_set = set(failed_pdd_ids)
    for target in targets:
        selector = str(target.get("product_selector") or "").strip()
        pdd_id = str(target.get("pdd_product_id") or "").strip()
        # 上架后可能新写入了 pdd，优先用成功集反查；此处以 targets 中更新值 + success 集为准
        batch_index = target.get("batch_index")
        matched_pdd = ""
        if pdd_id and pdd_id in success_set:
            matched_pdd = pdd_id
        elif pdd_id and pdd_id in failed_set:
            matched_pdd = pdd_id
        elif len(success_pdd_ids) == 1 and len(targets) == 1:
            matched_pdd = success_pdd_ids[0]
        elif len(failed_pdd_ids) == 1 and len(targets) == 1:
            matched_pdd = failed_pdd_ids[0]

        if matched_pdd and matched_pdd in success_set:
            status = STAGE_SUCCESS
            err = ""
        elif matched_pdd and matched_pdd in failed_set:
            status = STAGE_FAILED
            err = error or "挂回原链路限时失败"
        elif success_set and pdd_id in success_set:
            status = STAGE_SUCCESS
            err = ""
        else:
            # 若仅有一个成功且目标唯一，已在上面处理；否则不瞎改
            continue

        try:
            patch_batch_product_stage(
                pipeline_id=pipeline_id,
                batch_index=int(batch_index) if batch_index is not None else None,
                product_selector=selector,
                pdd_product_id=pdd_id or matched_pdd,
                limited_time_status=status,
                limited_time_error=err,
                set_pdd_product_id=matched_pdd or None,
            )
        except Exception:
            logger.exception(
                "attach retry patch limited_time failed pipeline=%s selector=%s",
                pipeline_id,
                selector,
            )


def _merge_success_into_activity_pool(
    row,
    *,
    run_id: str,
    result: dict[str, Any] | None,
    fallback_pdd_ids: list[str],
    fallback_mapping_ids: list[str],
) -> tuple[list[str], list[str]]:
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        META_ACTIVITY_PDD_IDS_KEY,
        META_LT_SUCCESS_MAPPING_IDS_KEY,
        META_LT_SUCCESS_PDD_IDS_KEY,
        LimitedTimeSuccessProducts,
        build_limited_time_success_meta_patch,
        extract_limited_time_success_products,
    )
    from pdd_agent.api.services.pipeline_lt_accumulate_success_for_activity_policy import (
        ACCUMULATED_MAPPING_IDS_KEY,
        ACCUMULATED_PDD_IDS_KEY,
    )
    from pdd_agent.api.services.pipeline_per_batch_lt_aggregate.constants import (
        AGG_MAPPING_IDS_KEY,
        AGG_PDD_IDS_KEY,
    )

    meta = _meta(row)
    extract = extract_limited_time_success_products(
        result,
        account_id=str(row.account_id or ""),
        fallback_pdd_ids=fallback_pdd_ids,
        fallback_mapping_ids=fallback_mapping_ids,
    )
    if not extract.pdd_product_ids and fallback_pdd_ids:
        extract = LimitedTimeSuccessProducts(
            pdd_product_ids=list(fallback_pdd_ids),
            mapping_ids=list(fallback_mapping_ids),
            source="attach_retry_fallback",
            detail="挂回原链路限时结果回退到上架成功商品",
        )

    existing_pdd = _merge_unique(
        list(meta.get(META_ACTIVITY_PDD_IDS_KEY) or [])
        + list(meta.get(META_LT_SUCCESS_PDD_IDS_KEY) or [])
        + list(meta.get(ACCUMULATED_PDD_IDS_KEY) or [])
        + list(meta.get(AGG_PDD_IDS_KEY) or [])
        + list(row.pdd_product_ids or [])
    )
    existing_map = _merge_unique(
        list(meta.get(META_LT_SUCCESS_MAPPING_IDS_KEY) or [])
        + list(meta.get(ACCUMULATED_MAPPING_IDS_KEY) or [])
        + list(meta.get(AGG_MAPPING_IDS_KEY) or [])
        + list(row.mapping_ids or [])
    )
    merged_pdd = _merge_unique([*existing_pdd, *extract.pdd_product_ids])
    merged_map = _merge_unique([*existing_map, *extract.mapping_ids])
    patch = build_limited_time_success_meta_patch(
        LimitedTimeSuccessProducts(
            pdd_product_ids=merged_pdd,
            mapping_ids=merged_map,
            source="failure_log_attach_retry_success",
            detail=f"挂回原链路限时成功 {len(extract.pdd_product_ids)}，活动池合计 {len(merged_pdd)}",
        )
    )
    patch[ACCUMULATED_PDD_IDS_KEY] = merged_pdd
    patch[ACCUMULATED_MAPPING_IDS_KEY] = merged_map
    patch[AGG_PDD_IDS_KEY] = merged_pdd
    patch[AGG_MAPPING_IDS_KEY] = merged_map
    patch["failure_log_attach_retry_limited_time_run_id"] = str(run_id or "").strip()
    update_integrated_pipeline(
        row.pipeline_id,
        pdd_product_ids=merged_pdd,
        mapping_ids=merged_map,
        meta_patch=patch,
    )
    return merged_pdd, merged_map


def _enqueue_limited_time(row, *, pdd_ids: list[str], mapping_ids: list[str]) -> str:
    limited_time_run_id = create_campaign_run(str(row.account_id or ""))
    enqueue_task(
        agent=AgentKind.CAMPAIGN.value,
        run_id=limited_time_run_id,
        account_id=str(row.account_id or ""),
        payload={
            "pipeline_id": row.pipeline_id,
            "campaign_type": "limited_time_setup",
            "pdd_product_ids": list(pdd_ids),
            "published_mapping_ids": list(mapping_ids),
            PAYLOAD_FLAG: True,
        },
        scheduled_at=datetime.now(),
    )
    _save_state(
        row,
        {
            "phase": PHASE_LIMITED_TIME,
            "limited_time_run_id": limited_time_run_id,
            "success_pdd_ids": list(pdd_ids),
            "success_mapping_ids": list(mapping_ids),
        },
    )
    update_integrated_pipeline(
        row.pipeline_id,
        status="running",
        current_step="limited_time_queued",
        error="",
    )
    return limited_time_run_id


def _complete_feishu_claim(row) -> None:
    state = attach_retry_state(row)
    record_id = str(state.get("feishu_record_id") or "").strip()
    if not record_id:
        return
    try:
        from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim import (
            release_cycle_relist_claim,
        )

        release_cycle_relist_claim(record_id)
        logger.info(
            "pipeline %s attach retry feishu claim completed record_id=%s",
            row.pipeline_id,
            record_id,
        )
    except Exception:
        logger.exception(
            "pipeline %s attach retry feishu claim release failed record_id=%s",
            row.pipeline_id,
            record_id,
        )


def start_attach_retry_on_source_pipeline(
    *,
    source_pipeline_id: str,
    merchant_code: str,
    account_id: str,
    feishu_record_id: str,
    material_source: str = "",
    skip_listing_if_on_sale: bool = True,
    already_on_sale_pdd_product_id: str = "",
) -> dict[str, Any]:
    """在原链路上启动挂回重跑。"""
    pipeline_id = str(source_pipeline_id or "").strip()
    row = get_integrated_pipeline(pipeline_id)
    if not row:
        raise ValueError("source_pipeline_not_found")

    state = attach_retry_state(row)
    if str(state.get("phase") or PHASE_IDLE) in ACTIVE_PHASES:
        raise ValueError("attach_retry_in_progress")

    from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger import (
        resolve_listing_selectors_for_merchant_code,
    )
    from pdd_agent.api.services.failure_log_attach_retry.resolve import resolve_attach_targets

    meta = _meta(row)
    selectors = resolve_listing_selectors_for_merchant_code(
        merchant_code,
        material_source=material_source or str(meta.get("material_source") or ""),
    )
    resolved = resolve_attach_targets(
        pipeline_id=pipeline_id,
        merchant_code=merchant_code,
        listing_selectors=selectors,
    )
    selectors = list(resolved.get("selectors") or selectors)
    if not selectors and merchant_code:
        selectors = [str(merchant_code).strip()]
    if not selectors:
        raise ValueError("no_listing_selectors")

    targets = list(resolved.get("targets") or [])
    account = str(account_id or row.account_id or "").strip()
    if not account:
        raise ValueError("account_id_missing")

    # 复活终态链路，允许继续活动改期
    status = str(getattr(row, "status", "") or "")
    if status in {"failed", "canceled", "completed"}:
        update_integrated_pipeline(
            pipeline_id,
            status="running",
            error="",
            meta_patch={
                "failure_log_attach_retry_revived_from": status,
            },
        )
        row = get_integrated_pipeline(pipeline_id) or row

    scheduled = getattr(row, "scheduled_activity_at", None)
    update_integrated_pipeline(
        pipeline_id,
        meta_patch={
            "failure_log_attach_retry_activity_defer": {
                "original_activity_at": scheduled.isoformat() if isinstance(scheduled, datetime) else "",
                "awaiting_reschedule": False,
            },
            "failure_log_attach_retry_feishu_record_id": str(feishu_record_id or "").strip(),
            "failure_log_attach_retry_merchant_code": str(merchant_code or "").strip(),
        },
    )

    # 已在售：跳过上架，直接精准改 listing 成功并进限时
    on_sale_pid = str(already_on_sale_pdd_product_id or "").strip()
    if skip_listing_if_on_sale and on_sale_pid:
        from pdd_agent.api.services.failure_log_attach_retry.stage_patch import patch_batch_product_stage
        from pdd_agent.api.services.pipeline_batch_product_stage_tracker import STAGE_SUCCESS
        from pdd_agent.api.services.pipeline_activity_limited_time_success import (
            resolve_mapping_ids_for_pdd_products,
        )

        for target in targets:
            try:
                patch_batch_product_stage(
                    pipeline_id=pipeline_id,
                    batch_index=int(target["batch_index"]) if target.get("batch_index") is not None else None,
                    product_selector=str(target.get("product_selector") or ""),
                    pdd_product_id=str(target.get("pdd_product_id") or ""),
                    listing_status=STAGE_SUCCESS,
                    listing_error="",
                    set_pdd_product_id=on_sale_pid,
                )
            except Exception:
                logger.exception("attach retry patch on-sale listing failed pipeline=%s", pipeline_id)
        mapping_ids = resolve_mapping_ids_for_pdd_products(account, [on_sale_pid])
        _save_state(
            row,
            {
                "phase": PHASE_LIMITED_TIME,
                "enabled": True,
                "feishu_record_id": str(feishu_record_id or "").strip(),
                "merchant_code": str(merchant_code or "").strip(),
                "selectors": selectors,
                "targets": targets,
                "batch_indices": list(resolved.get("batch_indices") or []),
                "listing_run_id": "",
                "limited_time_run_id": "",
                "started_at": datetime.now().isoformat(),
                "outcome": "",
                "outcome_detail": "already_on_sale_skip_listing",
                "success_pdd_ids": [on_sale_pid],
                "success_mapping_ids": mapping_ids,
            },
        )
        row = get_integrated_pipeline(pipeline_id) or row
        lt_run_id = _enqueue_limited_time(row, pdd_ids=[on_sale_pid], mapping_ids=mapping_ids)
        return {
            "pipeline_id": pipeline_id,
            "listing_run_id": "",
            "limited_time_run_id": lt_run_id,
            "selectors": selectors,
            "skipped_listing": True,
            "reason": "attach_retry_started_on_sale",
            "failure_log_attach_retry": build_attach_retry_public_state(
                get_integrated_pipeline(pipeline_id) or row
            ),
        }

    payload_base = _listing_payload_base(row)
    listing_run_id = create_listing_run(account)
    TaskRunStore().update_status(listing_run_id, RunStatus.PENDING, "failure log attach retry listing queued")

    _save_state(
        row,
        {
            "phase": PHASE_LISTING,
            "enabled": True,
            "feishu_record_id": str(feishu_record_id or "").strip(),
            "merchant_code": str(merchant_code or "").strip(),
            "selectors": selectors,
            "targets": targets,
            "batch_indices": list(resolved.get("batch_indices") or []),
            "listing_run_id": listing_run_id,
            "limited_time_run_id": "",
            "started_at": datetime.now().isoformat(),
            "outcome": "",
            "outcome_detail": "",
            "success_pdd_ids": [],
            "success_mapping_ids": [],
        },
    )

    enqueue_task(
        agent=AgentKind.LISTING.value,
        run_id=listing_run_id,
        account_id=account,
        payload={
            "product_codes": selectors,
            "dry_run": False,
            "category_keyword": str(payload_base.get("category_keyword") or "玩偶"),
            "platform_listing_code": "",
            "pipeline_id": pipeline_id,
            PAYLOAD_FLAG: True,
            "slot_alignment_test": bool(payload_base.get("slot_alignment_test")),
            "spec_fill_verify_test": bool(payload_base.get("spec_fill_verify_test")),
            "primary_style_first_test": bool(payload_base.get("primary_style_first_test")),
            "category_next_burst_demo": bool(payload_base.get("category_next_burst_demo", True)),
            "material_source": str(payload_base.get("material_source") or ""),
        },
        scheduled_at=datetime.now(),
    )
    update_integrated_pipeline(
        pipeline_id,
        status="running",
        current_step="listing_queued",
        listing_run_id=listing_run_id,
        error="",
    )
    logger.info(
        "pipeline %s attach retry started listing_run=%s selectors=%s feishu=%s",
        pipeline_id,
        listing_run_id,
        len(selectors),
        feishu_record_id,
    )
    refreshed = get_integrated_pipeline(pipeline_id) or row
    return {
        "pipeline_id": pipeline_id,
        "listing_run_id": listing_run_id,
        "limited_time_run_id": "",
        "selectors": selectors,
        "skipped_listing": False,
        "reason": "attach_retry_started",
        "failure_log_attach_retry": build_attach_retry_public_state(refreshed),
    }


def maybe_handle_attach_retry_listing_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    if not is_attach_retry_listing_run(row, run_id):
        return False

    result = result if isinstance(result, dict) else {}
    state = attach_retry_state(row)
    targets = list(state.get("targets") or [])
    pdd_ids, mapping_ids = _patch_targets_listing_success(
        pipeline_id=row.pipeline_id,
        targets=targets,
        result=result,
    )
    if not pdd_ids:
        detail = error or "挂回原链路上架无成功商品"
        _save_state(
            row,
            {
                "phase": PHASE_FAILED,
                "outcome": "listing_failed",
                "outcome_detail": detail,
            },
        )
        update_integrated_pipeline(
            row.pipeline_id,
            status="failed",
            current_step="listing_failed",
            error=detail,
        )
        return True

    # 刷新 targets 上的 pdd（下一阶段限时回写用）
    refreshed_targets = []
    for target in targets:
        item = dict(target)
        if not str(item.get("pdd_product_id") or "").strip() and len(pdd_ids) == 1:
            item["pdd_product_id"] = pdd_ids[0]
        refreshed_targets.append(item)

    _save_state(
        row,
        {
            "targets": refreshed_targets,
            "success_pdd_ids": pdd_ids,
            "success_mapping_ids": mapping_ids,
            "outcome": "listing_success",
            "outcome_detail": f"上架成功 {len(pdd_ids)} 个",
        },
    )
    row = get_integrated_pipeline(row.pipeline_id) or row
    lt_run_id = _enqueue_limited_time(row, pdd_ids=pdd_ids, mapping_ids=mapping_ids)
    logger.info(
        "pipeline %s attach retry listing done -> limited_time run=%s pdd=%s",
        row.pipeline_id,
        lt_run_id,
        len(pdd_ids),
    )
    return True


def maybe_handle_attach_retry_limited_time_finished(
    row,
    *,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    if not is_attach_retry_limited_time_run(row, run_id):
        return False

    from pdd_agent.api.services.failure_log_attach_retry.activity_policy import (
        maybe_finalize_activity_after_attach_retry,
        record_attach_retry_success_finished_at,
    )
    from pdd_agent.api.services.pipeline_activity_limited_time_success import (
        extract_limited_time_success_products,
        load_limited_time_run_result,
    )

    result = result if isinstance(result, dict) else load_limited_time_run_result(run_id)
    state = attach_retry_state(row)
    targets = list(state.get("targets") or [])
    fallback_pdd = list(state.get("success_pdd_ids") or [])
    fallback_map = list(state.get("success_mapping_ids") or [])

    extract = extract_limited_time_success_products(
        result,
        account_id=str(row.account_id or ""),
        fallback_pdd_ids=fallback_pdd,
        fallback_mapping_ids=fallback_map,
    )
    success_pdd = list(extract.pdd_product_ids)
    if not success_pdd and success and fallback_pdd:
        success_pdd = list(fallback_pdd)
    failed_pdd = [pid for pid in fallback_pdd if pid not in set(success_pdd)]

    # 同步 targets 里的 pdd_id，便于精准改状态
    patched_targets = []
    for target in targets:
        item = dict(target)
        if not str(item.get("pdd_product_id") or "").strip() and len(success_pdd) == 1:
            item["pdd_product_id"] = success_pdd[0]
        elif not str(item.get("pdd_product_id") or "").strip() and len(fallback_pdd) == 1:
            item["pdd_product_id"] = fallback_pdd[0]
        patched_targets.append(item)

    _patch_targets_limited_time(
        pipeline_id=row.pipeline_id,
        targets=patched_targets,
        success_pdd_ids=success_pdd,
        failed_pdd_ids=failed_pdd,
        error=error or "",
    )

    if success_pdd:
        _merge_success_into_activity_pool(
            row,
            run_id=run_id,
            result=result,
            fallback_pdd_ids=success_pdd,
            fallback_mapping_ids=fallback_map or list(extract.mapping_ids),
        )
        finished_at = datetime.now()
        record_attach_retry_success_finished_at(row, finished_at=finished_at)
        _save_state(
            row,
            {
                "targets": patched_targets,
                "phase": PHASE_DONE if not failed_pdd else PHASE_PARTIAL,
                "limited_time_run_id": "",
                "outcome": "limited_time_success",
                "outcome_detail": f"限时成功 {len(success_pdd)} 个",
                "last_success_finished_at": finished_at.isoformat(),
            },
        )
        refreshed = get_integrated_pipeline(row.pipeline_id) or row
        finalized = maybe_finalize_activity_after_attach_retry(refreshed)
        _complete_feishu_claim(get_integrated_pipeline(row.pipeline_id) or refreshed)
        logger.info(
            "pipeline %s attach retry limited_time done success=%s finalized=%s",
            row.pipeline_id,
            len(success_pdd),
            finalized,
        )
        return True

    detail = error or "挂回原链路限时无成功商品"
    _save_state(
        row,
        {
            "phase": PHASE_FAILED,
            "limited_time_run_id": "",
            "outcome": "limited_time_failed",
            "outcome_detail": detail,
        },
    )
    update_integrated_pipeline(
        row.pipeline_id,
        status="failed",
        current_step="limited_time_failed",
        error=detail,
    )
    return True


def dispatch_attach_retry_queue_task_finished(
    row,
    *,
    agent: str,
    run_id: str,
    success: bool,
    result: dict[str, Any] | None,
    error: str,
) -> bool:
    agent_name = str(agent or "").strip()
    if agent_name == AgentKind.LISTING.value and is_attach_retry_listing_run(row, run_id):
        return maybe_handle_attach_retry_listing_finished(
            row,
            run_id=run_id,
            success=success,
            result=result,
            error=error,
        )
    if agent_name == AgentKind.CAMPAIGN.value and is_attach_retry_limited_time_run(row, run_id):
        return maybe_handle_attach_retry_limited_time_finished(
            row,
            run_id=run_id,
            success=success,
            result=result,
            error=error,
        )
    return False
