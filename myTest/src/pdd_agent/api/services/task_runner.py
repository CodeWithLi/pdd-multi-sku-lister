"""LangGraph 任务执行服务。"""

from __future__ import annotations

import asyncio
from typing import Any

from pdd_agent.browser.sync_job import run_browser_job_async
from pdd_agent.agents.campaign import build_campaign_graph
from pdd_agent.agents.delist import build_delist_graph
from pdd_agent.agents.listing import build_listing_graph
from pdd_agent.agents.orchestrator import build_orchestrator_graph
from pdd_agent.agents.traffic import build_traffic_graph
from pdd_agent.api.schemas.tasks import PlanResponse
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import (
    get_account_config,
    get_published_product_by_mapping_id,
    patch_published_product_spec_metadata,
    update_published_product_status,
    upsert_published_product,
)
from pdd_agent.skills.published.goods_list_lookup import lookup_published_product_in_goods_list
from pdd_agent.domain.enums import AgentKind, RunStatus, TaskPhase
from pdd_agent.domain.models import PlannedTask
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)

_DB_MESSAGE_MAX = 2000
_DB_LARGE_TEXT_MAX = 500
_LARGE_RESULT_TEXT_KEYS = frozenset({
    "pdd_product_matched_row_text",
    "matched_row_text",
    "row_text",
})


def _json_safe(value: Any) -> Any:
    """把 graph 返回值转为可 JSON 序列化的结构。"""
    if isinstance(value, PlannedTask):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _truncate_db_text(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(共{len(text)}字)"


def _compact_value_for_storage(value: Any, key: str = "") -> Any:
    """落库前截断页面抓取等超大文本，避免撑爆 run_records。"""
    if isinstance(value, str):
        if key in _LARGE_RESULT_TEXT_KEYS:
            return _truncate_db_text(value, _DB_LARGE_TEXT_MAX)
        if len(value) > 2000:
            return _truncate_db_text(value, 2000)
        return value
    if isinstance(value, list):
        return [_compact_value_for_storage(item, "") for item in value]
    if isinstance(value, dict):
        return {k: _compact_value_for_storage(v, k) for k, v in value.items()}
    return value


def _compact_run_result_for_storage(result: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_value_for_storage(result)
    return compacted if isinstance(compacted, dict) else result


def _summarize_listing_message(result: dict[str, Any]) -> str:
    """上架任务 message 只存摘要，完整结果在 result 字段。"""
    errors = result.get("errors") or []
    if isinstance(errors, list):
        for item in errors:
            text = str(item or "").strip()
            if text:
                return _truncate_db_text(text, _DB_MESSAGE_MAX)
    items = [r for r in result.get("results") or [] if isinstance(r, dict)]
    if not items:
        return "上架任务完成"
    success = sum(1 for r in items if str(r.get("status") or "") in {"success", "listed"})
    failed = sum(1 for r in items if str(r.get("status") or "") == "failed")
    retryable = sum(1 for r in items if str(r.get("status") or "") == "retryable")
    parts = [f"共{len(items)}个单元", f"成功{success}", f"可重试{retryable}", f"失败{failed}"]
    for row in items:
        if str(row.get("status") or "") in {"success", "listed"}:
            continue
        label = str(row.get("listing_label") or "").strip()
        reason = str(row.get("reason") or row.get("error") or "").strip()
        if label or reason:
            parts.append(f"例：{label} {reason}".strip())
            break
    return _truncate_db_text("；".join(parts), _DB_MESSAGE_MAX)


def _summarize_delist_message(result: dict[str, Any]) -> str:
    errors = result.get("errors") or []
    if isinstance(errors, list):
        for item in errors:
            text = str(item or "").strip()
            if text:
                return _truncate_db_text(text, _DB_MESSAGE_MAX)
    items = result.get("results")
    if isinstance(items, list) and items:
        return _truncate_db_text(f"下架处理 {len(items)} 条", _DB_MESSAGE_MAX)
    return "下架任务完成"


def _summarize_campaign_message(result: dict[str, Any]) -> str:
    """活动任务失败时只存简短说明，避免把整份 results JSON 写入 message。"""
    item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
    for item in item_results:
        reg_msg = _activity_registration_summary_line(item)
        if reg_msg:
            return reg_msg

    errors = result.get("errors") or []
    if isinstance(errors, list):
        for item in errors:
            text = str(item or "").strip()
            if text:
                return text
    for item in item_results:
        if str(item.get("status") or "") == "success":
            continue
        err = str(item.get("error") or "").strip()
        if err:
            step = str(item.get("step") or "").strip()
            return f"{step}: {err}" if step else err
    if item_results and all(str(r.get("status") or "") == "success" for r in item_results):
        return "活动任务已完成"
    return "活动任务失败"


def _activity_registration_summary_line(item: dict[str, Any]) -> str:
    """从单次活动报名结果生成一眼可读的摘要。"""
    step = str(item.get("step") or "").strip()
    if step == "price_page_prepared":
        return "仅完成规格反查，未点击确认提交"

    product_ids = [
        str(pid).strip()
        for pid in (item.get("product_ids") or [])
        if str(pid).strip()
    ]
    selected = len(product_ids)

    finalize = item.get("finalize_result") if isinstance(item.get("finalize_result"), dict) else {}
    price_filter = finalize.get("price_filter") if isinstance(finalize.get("price_filter"), dict) else {}
    if not price_filter and isinstance(item.get("price_filter"), dict):
        price_filter = item["price_filter"]

    verify = finalize.get("submit_verification") if isinstance(finalize.get("submit_verification"), dict) else {}

    submitted = False
    if isinstance(finalize.get("confirm_submit"), dict) and finalize["confirm_submit"].get("clicked"):
        submitted = verify.get("verified") is not False
    elif step == "register_completed" and str(item.get("status") or "") == "success":
        submitted = verify.get("verified") is not False

    if str(item.get("status") or "") == "cancelled" or finalize.get("status") == "cancelled":
        return "未提交报名：全部商品不符合条件"
    if finalize.get("status") == "failed":
        err = str(finalize.get("error") or "").strip()
        if err:
            return err
        if verify.get("verified") is False:
            return "已点击确认提交，但拼多多未受理（可能仍有不合格规格）"
        return "报名未完成"
    if price_filter.get("action") == "partial_invalid_needs_manual":
        err = str(price_filter.get("error") or "").strip()
        return err.split("\n")[0] if err else "部分商品未能从活动页删除，未提交报名"
    if price_filter.get("status") == "all_products_removed":
        summary = str(price_filter.get("filter_summary") or price_filter.get("error") or "").strip()
        if summary:
            return summary.split("\n")[0]
        return "未提交报名：所选商品均含不合格规格，已整商品剔除"

    validation = price_filter.get("validation") if isinstance(price_filter.get("validation"), dict) else {}
    results = validation.get("results") if isinstance(validation.get("results"), list) else []
    passed_specs = sum(
        1
        for row in results
        if isinstance(row, dict) and row.get("valid") is True and not row.get("should_remove")
    )
    failed_specs = sum(
        1
        for row in results
        if isinstance(row, dict) and (row.get("should_remove") or row.get("valid") is False)
    )

    filter_result = price_filter.get("filter_result") if isinstance(price_filter.get("filter_result"), dict) else {}
    partial_ids = {
        str(pid).strip()
        for pid in (filter_result.get("partial_product_ids") or [])
        if str(pid).strip()
    }
    removed_ids = {
        str(pid).strip()
        for pid in (filter_result.get("removed_product_ids") or [])
        if str(pid).strip()
    }
    skipped_delete = bool(price_filter.get("action") == "partial_invalid_needs_manual")

    if submitted:
        submitted_products = 0
        blocked_products = 0
        removed_products = 0
        by_product: dict[str, list[dict[str, Any]]] = {}
        for row in results:
            if not isinstance(row, dict):
                continue
            pid = str(row.get("pdd_product_id") or row.get("page_product_id") or "").strip()
            by_product.setdefault(pid, []).append(row)

        keys = product_ids or list(by_product.keys())
        for pid in keys:
            rows = by_product.get(pid, [])
            passed = sum(1 for row in rows if row.get("valid") is True and not row.get("should_remove"))
            failed = sum(1 for row in rows if row.get("should_remove") or row.get("valid") is False)
            if pid in removed_ids or (failed > 0 and passed == 0):
                removed_products += 1
            elif passed > 0:
                submitted_products += 1

        if submitted_products <= 0:
            return "未有任何商品完成报名"
        parts = [f"报名已提交：{submitted_products}/{selected or submitted_products} 个商品"]
        if blocked_products:
            parts.append(f"{blocked_products} 个待核对")
        if removed_products:
            parts.append(f"{removed_products} 个未报名")
        if failed_specs:
            parts.append(f"规格 {passed_specs}/{passed_specs + failed_specs} 合格")
        return "；".join(parts)

    if step in {"register_completed", "product_pick_confirmed"} and str(item.get("status") or "") == "success":
        return "活动任务已完成"
    return ""


def _summarize_traffic_message(result: dict[str, Any]) -> str:
    """推广任务失败时只存简短说明。"""
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
        err = str(item.get("error") or "").strip()
        if err:
            step = str(item.get("step") or "").strip()
            return f"{step}: {err}" if step else err
    if item_results and all(str(r.get("status") or "") == "success" for r in item_results):
        return "推广任务已完成"
    return "推广任务失败"


def plan_tasks(message: str) -> PlanResponse:
    graph = build_orchestrator_graph()
    result = graph.invoke({"user_message": message})
    tasks = result.get("planned_tasks") or []
    return PlanResponse(
        plan_summary=result.get("plan_summary") or "",
        planned_tasks=[t.model_dump(mode="json") for t in tasks],
    )


def persist_published_item(run_id: str, account_id: str, item: dict[str, Any]) -> None:
    """单个上架成功结果写入 published_products（支持批次中途取消/中断）。"""
    if not isinstance(item, dict):
        return
    if str(item.get("status") or "") not in {"success", "listed"}:
        return
    pdd_product_id = str(item.get("pdd_product_id") or "").strip()
    if not pdd_product_id:
        return
    product_code = str(item.get("product_code") or "").strip()
    family_code = str(item.get("family_code") or "").strip()
    image_set = str(item.get("image_set") or "").strip()
    listing_label = str(item.get("listing_label") or "").strip()
    merchant_code = str(
        item.get("platform_listing_code") or item.get("merchant_code") or ""
    ).strip()
    if not product_code or not listing_label:
        return
    upsert_published_product(
        account_id=account_id,
        source_run_id=run_id,
        product_code=product_code,
        family_code=family_code,
        image_set=image_set,
        listing_label=listing_label,
        merchant_code=merchant_code,
        pdd_product_id=pdd_product_id,
        spec_metadata=item.get("spec_metadata") if isinstance(item.get("spec_metadata"), dict) else {},
    )


def _persist_published_products(run_id: str, account_id: str, result: dict[str, Any]) -> None:
    for item in result.get("results") or []:
        persist_published_item(run_id, account_id, item)


async def execute_listing(
    *,
    run_id: str,
    account_id: str,
    product_codes: list[str],
    dry_run: bool,
    category_keyword: str,
    platform_listing_code: str = "",
    retry_item: dict[str, Any] | None = None,
    slot_alignment_test: bool = False,
) -> dict[str, Any]:
    """执行 listing 子图，更新 RunRecord。"""
    store = TaskRunStore()
    settings = load_yaml_settings()
    account = get_account_config(settings, account_id)
    if not account:
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        return {"error": f"unknown account: {account_id}"}

    codes = product_codes or account.product_codes
    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.PREFLIGHT)

    try:
        graph = build_listing_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "product_codes": codes,
                "platform_listing_code": platform_listing_code,
                "dry_run": dry_run,
                "category_keyword": category_keyword,
                "retry_item": retry_item or {},
                "run_id": run_id,
                "slot_alignment_test": slot_alignment_test,
            }
        )
        result = _json_safe(raw)
        # 批次内已成功的商品先落库，避免取消/中断时丢失
        _persist_published_products(run_id, account_id, result)
        record = store.load(run_id)
        if record and record.status == RunStatus.CANCELED:
            return {"canceled": True, "results": result.get("results") or []}
        labels = []
        for u in result.get("units") or []:
            if isinstance(u, dict) and u.get("listing_label"):
                labels.append(u["listing_label"])
        for r in result.get("results") or []:
            if isinstance(r, dict) and r.get("listing_label"):
                labels.append(r["listing_label"])

        item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
        item_failed = any(r.get("status") in {"failed", "retryable"} for r in item_results)
        status = RunStatus.SUCCESS if not result.get("errors") and not item_failed else RunStatus.FAILED
        try:
            from pdd_agent.api.services.listing_failure_log import persist_listing_run_failures

            persist_listing_run_failures(
                source_run_id=run_id,
                account_id=account_id,
                result=result,
            )
        except Exception:
            logger.warning("persist listing failure details failed run_id=%s", run_id)
        store.finish(
            run_id,
            status,
            message=_summarize_listing_message(result),
            result=_compact_run_result_for_storage(result),
            listing_labels=labels,
        )
        from pdd_agent.api.services.run_cancel import clear_cancel

        clear_cancel(run_id)
        return result
    except asyncio.CancelledError:
        store.update_status(run_id, RunStatus.CANCELED, "canceled by user")
        raise
    except Exception as exc:
        logger.exception("listing job failed run_id=%s", run_id)
        store.finish(run_id, RunStatus.FAILED, str(exc), result={"error": str(exc)})
        return {"error": str(exc)}


def create_listing_run(account_id: str) -> str:
    store = TaskRunStore()
    return store.create_run(AgentKind.LISTING, account_id).run_id


def _sync_single_delist_result(result: dict[str, Any]) -> None:
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        mapping_id = str(item.get("mapping_id") or "").strip()
        if not mapping_id:
            continue
        if item.get("status") == "delisted" and not item.get("error"):
            update_published_product_status(mapping_id, "delisted")


async def execute_delist(
    *,
    run_id: str,
    account_id: str,
    dry_run: bool | None = None,
    delist_params: dict | None = None,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    if not get_account_config(settings, account_id):
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        return {"error": f"unknown account: {account_id}"}

    params = delist_params or {}
    if dry_run is not None:
        params["dry_run"] = dry_run

    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.BROWSER)
    try:
        graph = build_delist_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "dry_run": params.get("dry_run", settings.delist.dry_run),
                "delist_params": params,
            }
        )
        result = _json_safe(raw)
        status = RunStatus.SUCCESS if not result.get("errors") else RunStatus.FAILED
        if status == RunStatus.SUCCESS:
            _sync_single_delist_result(result)
        store.finish(
            run_id,
            status,
            message=_summarize_delist_message(result),
            result=_compact_run_result_for_storage(result),
        )
        return result
    except asyncio.CancelledError:
        store.update_status(run_id, RunStatus.CANCELED, "canceled by user")
        raise
    except Exception as exc:
        logger.exception("delist job failed run_id=%s", run_id)
        store.finish(run_id, RunStatus.FAILED, str(exc), result={"error": str(exc)})
        return {"error": str(exc)}


def create_delist_run(account_id: str) -> str:
    store = TaskRunStore()
    return store.create_run(AgentKind.DELIST, account_id).run_id


def create_published_goods_lookup_run(account_id: str) -> str:
    store = TaskRunStore()
    return store.create_run(AgentKind.LISTING, account_id).run_id


async def execute_published_goods_lookup(
    *,
    run_id: str,
    account_id: str,
    mapping_id: str,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    account = get_account_config(settings, account_id)
    if not account:
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        return {"error": f"unknown account: {account_id}"}

    row = get_published_product_by_mapping_id(mapping_id)
    if not row:
        store.finish(run_id, RunStatus.FAILED, f"published product not found: {mapping_id}")
        return {"error": f"published product not found: {mapping_id}"}
    if not row.pdd_product_id:
        store.finish(run_id, RunStatus.FAILED, "published product has no pdd_product_id")
        return {"error": "published product has no pdd_product_id"}

    store.update_status(run_id, RunStatus.RUNNING, "published goods lookup")
    store.update_phase(run_id, TaskPhase.BROWSER)
    pdd_product_id = str(row.pdd_product_id).strip()

    def _job(dp):
        return lookup_published_product_in_goods_list(dp, account_id, pdd_product_id)

    try:
        result = await run_browser_job_async(settings, account, _job)
        lookup_payload = result.get("pdd_goods_lookup")
        if isinstance(lookup_payload, dict):
            patch_published_product_spec_metadata(mapping_id, {"pdd_goods_lookup": lookup_payload})

        if str(result.get("status") or "") == "success":
            store.finish(
                run_id,
                RunStatus.SUCCESS,
                message=str(result.get("message") or f"goods lookup ok product_id={pdd_product_id}"),
                result=_json_safe(result),
            )
            return result

        error = str(result.get("error") or "published goods lookup failed")
        store.finish(run_id, RunStatus.FAILED, error, result=_json_safe(result))
        return result
    except Exception as exc:
        logger.exception("published goods lookup failed run_id=%s mapping_id=%s", run_id, mapping_id)
        store.finish(run_id, RunStatus.FAILED, str(exc), result={"error": str(exc)})
        return {"error": str(exc)}


async def execute_campaign_marketing_activity_register(
    *,
    run_id: str,
    account_id: str,
    activity_id: str,
    pdd_product_ids: list[str] | None = None,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    if not get_account_config(settings, account_id):
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        return {"error": f"unknown account: {account_id}"}

    activity_id = str(activity_id or "").strip()
    selected_product_ids = list(dict.fromkeys(pdd_product_ids or []))
    if not activity_id:
        store.finish(run_id, RunStatus.FAILED, "activity_id is required")
        return {"error": "activity_id is required"}
    if not selected_product_ids:
        store.finish(run_id, RunStatus.FAILED, "pdd_product_ids is required")
        return {"error": "pdd_product_ids is required"}

    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.BROWSER)
    try:
        graph = build_campaign_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "campaign_type": "marketing_activity_register",
                "marketing_activity_id": activity_id,
                "pdd_product_ids": selected_product_ids,
            }
        )
        result = _json_safe(raw)
        item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
        item_failed = any(str(r.get("status") or "") != "success" for r in item_results)
        status = RunStatus.SUCCESS if not result.get("errors") and not item_failed else RunStatus.FAILED
        store.finish(run_id, status, message=_summarize_campaign_message(result), result=result)
        return result
    except Exception as exc:
        logger.exception("campaign marketing activity register failed run_id=%s", run_id)
        store.finish(run_id, RunStatus.FAILED, str(exc), result={"error": str(exc)})
        return {"error": str(exc)}


async def execute_campaign_marketing_activity_search(
    *,
    run_id: str,
    account_id: str,
    activity_id: str,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    if not get_account_config(settings, account_id):
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        return {"error": f"unknown account: {account_id}"}

    activity_id = str(activity_id or "").strip()
    if not activity_id:
        store.finish(run_id, RunStatus.FAILED, "activity_id is required")
        return {"error": "activity_id is required"}

    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.BROWSER)
    try:
        graph = build_campaign_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "campaign_type": "marketing_activity_search",
                "marketing_activity_id": activity_id,
            }
        )
        result = _json_safe(raw)
        item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
        item_failed = any(str(r.get("status") or "") != "success" for r in item_results)
        status = RunStatus.SUCCESS if not result.get("errors") and not item_failed else RunStatus.FAILED
        store.finish(run_id, status, message=_summarize_campaign_message(result), result=result)
        return result
    except Exception as exc:
        logger.exception("campaign marketing activity search failed run_id=%s", run_id)
        store.finish(run_id, RunStatus.FAILED, str(exc), result={"error": str(exc)})
        return {"error": str(exc)}


async def execute_campaign_limited_time_setup(
    *,
    run_id: str,
    account_id: str,
    pdd_product_ids: list[str] | None = None,
    published_mapping_ids: list[str] | None = None,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    if not get_account_config(settings, account_id):
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        return {"error": f"unknown account: {account_id}"}

    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.BROWSER)
    selected_product_ids = list(dict.fromkeys((pdd_product_ids or [])))
    selected_mapping_ids = list(dict.fromkeys((published_mapping_ids or [])))
    try:
        graph = build_campaign_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "campaign_type": "limited_time_setup",
                "pdd_product_ids": selected_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }
        )
        result = _json_safe(raw)
        item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
        item_failed = any(str(r.get("status") or "") != "success" for r in item_results)
        status = RunStatus.SUCCESS if not result.get("errors") and not item_failed else RunStatus.FAILED
        store.finish(run_id, status, message=_summarize_campaign_message(result), result=result)
        return result
    except Exception as exc:
        logger.exception("campaign job failed run_id=%s", run_id)
        store.finish(run_id, RunStatus.FAILED, str(exc), result={"error": str(exc)})
        return {"error": str(exc)}


def create_campaign_run(account_id: str) -> str:
    store = TaskRunStore()
    return store.create_run(AgentKind.CAMPAIGN, account_id).run_id


async def execute_traffic_promotion_create(
    *,
    run_id: str,
    account_id: str,
    pdd_product_ids: list[str] | None = None,
    published_mapping_ids: list[str] | None = None,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    if not get_account_config(settings, account_id):
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        return {"error": f"unknown account: {account_id}"}

    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.BROWSER)
    selected_product_ids = list(dict.fromkeys(pdd_product_ids or []))
    selected_mapping_ids = list(dict.fromkeys(published_mapping_ids or []))
    try:
        graph = build_traffic_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "traffic_type": "promotion_create",
                "pdd_product_ids": selected_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }
        )
        result = _json_safe(raw)
        item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
        item_failed = any(str(r.get("status") or "") != "success" for r in item_results)
        status = RunStatus.SUCCESS if not result.get("errors") and not item_failed else RunStatus.FAILED
        store.finish(run_id, status, message=_summarize_traffic_message(result), result=result)
        return result
    except Exception as exc:
        logger.exception("traffic promotion create failed run_id=%s", run_id)
        store.finish(run_id, RunStatus.FAILED, str(exc), result={"error": str(exc)})
        return {"error": str(exc)}


def create_traffic_run(account_id: str) -> str:
    store = TaskRunStore()
    return store.create_run(AgentKind.TRAFFIC, account_id).run_id
