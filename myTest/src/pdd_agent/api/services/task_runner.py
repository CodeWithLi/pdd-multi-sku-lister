"""LangGraph 任务执行服务。"""

from __future__ import annotations

from typing import Any

from pdd_agent.agents.campaign import build_campaign_graph
from pdd_agent.agents.delist import build_delist_graph
from pdd_agent.agents.listing import build_listing_graph
from pdd_agent.agents.orchestrator import build_orchestrator_graph
from pdd_agent.api.schemas.tasks import PlanResponse
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import (
    get_account_config,
    update_published_product_status,
    upsert_published_product,
)
from pdd_agent.domain.enums import AgentKind, RunStatus, TaskPhase
from pdd_agent.domain.models import PlannedTask
from pdd_agent.storage import TaskRunStore

logger = get_logger(__name__)


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


def plan_tasks(message: str) -> PlanResponse:
    graph = build_orchestrator_graph()
    result = graph.invoke({"user_message": message})
    tasks = result.get("planned_tasks") or []
    return PlanResponse(
        plan_summary=result.get("plan_summary") or "",
        planned_tasks=[t.model_dump(mode="json") for t in tasks],
    )


def _persist_published_products(run_id: str, account_id: str, result: dict[str, Any]) -> None:
    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") not in {"success", "listed"}:
            continue
        pdd_product_id = str(item.get("pdd_product_id") or "").strip()
        if not pdd_product_id:
            continue
        product_code = str(item.get("product_code") or "").strip()
        image_set = str(item.get("image_set") or "").strip()
        listing_label = str(item.get("listing_label") or "").strip()
        merchant_code = str(
            item.get("platform_listing_code") or item.get("merchant_code") or ""
        ).strip()
        if not product_code or not listing_label:
            continue
        upsert_published_product(
            account_id=account_id,
            source_run_id=run_id,
            product_code=product_code,
            image_set=image_set,
            listing_label=listing_label,
            merchant_code=merchant_code,
            pdd_product_id=pdd_product_id,
        )


async def execute_listing(
    *,
    run_id: str,
    account_id: str,
    product_codes: list[str],
    dry_run: bool,
    category_keyword: str,
    platform_listing_code: str = "",
    retry_item: dict[str, Any] | None = None,
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
            }
        )
        result = _json_safe(raw)
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
        _persist_published_products(run_id, account_id, result)
        store.finish(
            run_id,
            status,
            message=str(result.get("results") or result.get("errors") or ""),
            result=result,
            listing_labels=labels,
        )
        return result
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
        store.finish(run_id, status, message=str(result.get("results") or ""), result=result)
        return result
    except Exception as exc:
        logger.exception("delist job failed run_id=%s", run_id)
        store.finish(run_id, RunStatus.FAILED, str(exc), result={"error": str(exc)})
        return {"error": str(exc)}


def create_delist_run(account_id: str) -> str:
    store = TaskRunStore()
    return store.create_run(AgentKind.DELIST, account_id).run_id


async def execute_campaign_limited_time_setup(
    *,
    run_id: str,
    account_id: str,
) -> dict[str, Any]:
    store = TaskRunStore()
    settings = load_yaml_settings()
    if not get_account_config(settings, account_id):
        store.finish(run_id, RunStatus.FAILED, f"unknown account: {account_id}")
        return {"error": f"unknown account: {account_id}"}

    store.update_status(run_id, RunStatus.RUNNING)
    store.update_phase(run_id, TaskPhase.BROWSER)
    try:
        graph = build_campaign_graph()
        raw = await graph.ainvoke(
            {
                "account_id": account_id,
                "campaign_type": "limited_time_setup",
            }
        )
        result = _json_safe(raw)
        item_results = [r for r in result.get("results") or [] if isinstance(r, dict)]
        item_failed = any(str(r.get("status") or "") != "success" for r in item_results)
        status = RunStatus.SUCCESS if not result.get("errors") and not item_failed else RunStatus.FAILED
        store.finish(run_id, status, message=str(result.get("results") or ""), result=result)
        return result
    except Exception as exc:
        logger.exception("campaign job failed run_id=%s", run_id)
        store.finish(run_id, RunStatus.FAILED, str(exc), result={"error": str(exc)})
        return {"error": str(exc)}


def create_campaign_run(account_id: str) -> str:
    store = TaskRunStore()
    return store.create_run(AgentKind.CAMPAIGN, account_id).run_id
