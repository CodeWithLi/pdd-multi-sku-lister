"""分阶段流水线各阶段执行（独立调用上架/活动/推广，不走整合链路）。"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from pdd_agent.api.services.task_runner import (
    create_campaign_run,
    create_listing_run,
    create_traffic_run,
    execute_campaign_limited_time_setup,
    execute_campaign_marketing_activity_register,
    execute_listing,
    execute_traffic_promotion_create,
)
from pdd_agent.core.logging import get_logger
from pdd_agent.db.models import FailureSequentialJobORM, PublishedProductORM
from pdd_agent.db.session import session_scope
from pdd_agent.domain.enums import RunStatus
from pdd_agent.failure_sequential.constants import (
    ACTIVITY_618_ID,
    ACTIVITY_DISCOUNT_ID,
    STAGE_FAILED,
    STAGE_SKIPPED,
    STAGE_SUCCESS,
)
from pdd_agent.integrations.feishu.config import PddFailureCycleRelistWatchConfig
from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_trigger import (
    check_merchant_code_already_on_sale,
    resolve_listing_selectors_for_merchant_code,
)
from pdd_agent.storage.task_store import TaskRunStore

logger = get_logger(__name__)


def _truncate_error(text: str, limit: int = 1500) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw
    return f"{raw[:limit]}...(共{len(raw)}字)"


def _extract_result_error(result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict):
        return "任务返回为空"
    err = str(result.get("error") or "").strip()
    if err:
        return err
    errors = result.get("errors") or []
    if isinstance(errors, list):
        for item in errors:
            text = str(item or "").strip()
            if text:
                return text
    item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
    for item in item_results:
        if str(item.get("status") or "") == "success":
            continue
        row_err = str(item.get("error") or "").strip()
        if row_err:
            return row_err
    return "任务执行失败"


def _listing_success_item(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") in {"success", "listed"}:
            return item
    return None


def _resolve_published_ids(
    *,
    account_id: str,
    merchant_code: str,
    listing_result: dict[str, Any] | None = None,
) -> tuple[str, str]:
    item = _listing_success_item(listing_result)
    if item:
        pid = str(item.get("pdd_product_id") or "").strip()
        mid = str(item.get("mapping_id") or "").strip()
        if pid:
            return pid, mid

    code = str(merchant_code or "").strip()
    aid = str(account_id or "").strip()
    if code and aid:
        try:
            listed = check_merchant_code_already_on_sale(account_id=aid, merchant_code=code)
            if listed.get("listed"):
                return str(listed.get("pdd_product_id") or "").strip(), ""
        except Exception as exc:
            logger.warning(
                "resolve published via goods list failed account=%s merchant=%s error=%s",
                aid,
                code,
                exc,
            )

        with session_scope() as session:
            row = session.execute(
                select(PublishedProductORM)
                .where(
                    PublishedProductORM.account_id == aid,
                    PublishedProductORM.merchant_code == code,
                )
                .order_by(PublishedProductORM.updated_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row:
                return str(row.pdd_product_id or "").strip(), str(row.mapping_id or "").strip()
    return "", ""


def _run_async(coro):
    return asyncio.run(coro)


def run_listing_stage(
    job: FailureSequentialJobORM,
    *,
    watch: PddFailureCycleRelistWatchConfig,
) -> dict[str, Any]:
    """执行上架阶段；任何异常均捕获并返回失败信息，不向外抛出。"""
    account_id = str(job.account_id or "").strip()
    merchant_code = str(job.merchant_code or "").strip()
    out: dict[str, Any] = {
        "status": STAGE_FAILED,
        "error": "",
        "run_id": "",
        "pdd_product_id": "",
        "mapping_id": "",
    }
    if not account_id or not merchant_code:
        out["error"] = "account_id 或 merchant_code 为空"
        return out

    try:
        listed = check_merchant_code_already_on_sale(
            account_id=account_id,
            merchant_code=merchant_code,
        )
        if listed.get("checked") and listed.get("listed"):
            pid = str(listed.get("pdd_product_id") or "").strip()
            out.update(status=STAGE_SKIPPED, pdd_product_id=pid, error="已在售，跳过上架")
            return out
    except Exception as exc:
        logger.warning("listing precheck failed job=%s error=%s", job.job_id, exc)

    material_source = str(watch.pipeline_material_source or "minio").strip() or "minio"
    product_codes = list(job.product_codes or [])
    if not product_codes:
        product_codes = resolve_listing_selectors_for_merchant_code(
            merchant_code,
            material_source=material_source,
        )
    if not product_codes:
        product_codes = [merchant_code]

    run_id = create_listing_run(account_id)
    out["run_id"] = run_id
    try:
        result = _run_async(
            execute_listing(
                run_id=run_id,
                account_id=account_id,
                product_codes=product_codes,
                dry_run=False,
                category_keyword=str(watch.pipeline_category_keyword or "玩偶"),
                platform_listing_code=merchant_code,
                slot_alignment_test=bool(watch.pipeline_slot_alignment_test),
                material_source=material_source or None,
            )
        )
    except Exception as exc:
        logger.exception("execute_listing failed job=%s run_id=%s", job.job_id, run_id)
        out["error"] = _truncate_error(str(exc))
        return out

    record = TaskRunStore().load(run_id)
    run_status = record.status if record else RunStatus.FAILED
    pid, mid = _resolve_published_ids(
        account_id=account_id,
        merchant_code=merchant_code,
        listing_result=result if isinstance(result, dict) else {},
    )
    out["pdd_product_id"] = pid
    out["mapping_id"] = mid

    if run_status == RunStatus.SUCCESS and pid:
        out["status"] = STAGE_SUCCESS
        return out

    if pid and run_status in {RunStatus.SUCCESS, RunStatus.FAILED}:
        out["status"] = STAGE_SUCCESS if run_status == RunStatus.SUCCESS else STAGE_FAILED
        if out["status"] == STAGE_FAILED:
            out["error"] = _truncate_error(_extract_result_error(result if isinstance(result, dict) else {}))
        return out

    out["status"] = STAGE_FAILED
    out["error"] = _truncate_error(
        _extract_result_error(result if isinstance(result, dict) else {})
        or (record.message if record else "上架未产出 pdd_product_id")
    )
    return out


def _require_product_id(job: FailureSequentialJobORM) -> tuple[str, str, str] | None:
    pid = str(job.pdd_product_id or "").strip()
    if not pid:
        return None
    mid = str(job.mapping_id or "").strip()
    aid = str(job.account_id or "").strip()
    if not aid:
        return None
    return aid, pid, mid


def run_limited_time_stage(job: FailureSequentialJobORM) -> dict[str, Any]:
    out: dict[str, Any] = {"status": STAGE_FAILED, "error": "", "run_id": ""}
    resolved = _require_product_id(job)
    if not resolved:
        out.update(status=STAGE_SKIPPED, error="无上架商品 ID，跳过限时限量购")
        return out
    account_id, pid, mid = resolved
    run_id = create_campaign_run(account_id)
    out["run_id"] = run_id
    try:
        result = _run_async(
            execute_campaign_limited_time_setup(
                run_id=run_id,
                account_id=account_id,
                pdd_product_ids=[pid],
                published_mapping_ids=[mid] if mid else [],
            )
        )
        record = TaskRunStore().load(run_id)
        ok = record and record.status == RunStatus.SUCCESS
        if ok:
            out["status"] = STAGE_SUCCESS
        else:
            out["status"] = STAGE_FAILED
            out["error"] = _truncate_error(_extract_result_error(result if isinstance(result, dict) else {}))
    except Exception as exc:
        logger.exception("limited_time failed job=%s", job.job_id)
        out["error"] = _truncate_error(str(exc))
    return out


def run_activity_stage(job: FailureSequentialJobORM, *, activity_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {"status": STAGE_FAILED, "error": "", "run_id": ""}
    resolved = _require_product_id(job)
    if not resolved:
        out.update(status=STAGE_SKIPPED, error="无上架商品 ID，跳过活动报名")
        return out
    account_id, pid, _mid = resolved
    run_id = create_campaign_run(account_id)
    out["run_id"] = run_id
    try:
        result = _run_async(
            execute_campaign_marketing_activity_register(
                run_id=run_id,
                account_id=account_id,
                activity_id=activity_id,
                pdd_product_ids=[pid],
            )
        )
        record = TaskRunStore().load(run_id)
        ok = record and record.status == RunStatus.SUCCESS
        if ok:
            out["status"] = STAGE_SUCCESS
        else:
            out["status"] = STAGE_FAILED
            out["error"] = _truncate_error(_extract_result_error(result if isinstance(result, dict) else {}))
    except Exception as exc:
        logger.exception("activity register failed job=%s activity=%s", job.job_id, activity_id)
        out["error"] = _truncate_error(str(exc))
    return out


def run_promotion_stage(job: FailureSequentialJobORM) -> dict[str, Any]:
    out: dict[str, Any] = {"status": STAGE_FAILED, "error": "", "run_id": ""}
    resolved = _require_product_id(job)
    if not resolved:
        out.update(status=STAGE_SKIPPED, error="无上架商品 ID，跳过推广")
        return out
    account_id, pid, mid = resolved
    run_id = create_traffic_run(account_id)
    out["run_id"] = run_id
    try:
        result = _run_async(
            execute_traffic_promotion_create(
                run_id=run_id,
                account_id=account_id,
                pdd_product_ids=[pid],
                published_mapping_ids=[mid] if mid else [],
            )
        )
        record = TaskRunStore().load(run_id)
        ok = record and record.status == RunStatus.SUCCESS
        if ok:
            out["status"] = STAGE_SUCCESS
        else:
            out["status"] = STAGE_FAILED
            out["error"] = _truncate_error(_extract_result_error(result if isinstance(result, dict) else {}))
    except Exception as exc:
        logger.exception("promotion failed job=%s", job.job_id)
        out["error"] = _truncate_error(str(exc))
    return out


def default_activity_ids(watch: PddFailureCycleRelistWatchConfig) -> tuple[str, str]:
    ids = [str(x).strip() for x in (watch.pipeline_activity_ids or []) if str(x).strip()]
    if len(ids) >= 2:
        return ids[0], ids[1]
    if len(ids) == 1:
        return ids[0], ACTIVITY_DISCOUNT_ID
    return ACTIVITY_618_ID, ACTIVITY_DISCOUNT_ID
