"""Delist Agent — 登录后扫描在售商品并下架。"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from pdd_agent.agents.state import DelistState
from pdd_agent.browser.sync_job import run_browser_job_async
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_account_config
from pdd_agent.skills.delist.automation import (
    DelistSettings,
    process_account_delist,
    process_single_product_delist,
)

logger = get_logger(__name__)


async def delist_browser_node(state: DelistState) -> dict:
    settings = load_yaml_settings()
    account_id = state["account_id"]
    account = get_account_config(settings, account_id)
    if not account:
        return {"errors": [f"unknown account: {account_id}"], "finished": True}

    raw = state.get("delist_params") or {}
    mode = str(raw.get("mode") or "").strip()
    target_product_id = str(raw.get("target_product_id") or "").strip()
    target_mapping_id = str(raw.get("target_mapping_id") or "").strip()
    target_merchant_code = str(raw.get("merchant_code") or "").strip()
    ds = DelistSettings(
        min_created_after=raw.get("min_created_after") or settings.delist.min_created_after,
        dry_run=raw.get("dry_run", settings.delist.dry_run),
        merchant_code_contains=raw.get("merchant_code_contains")
        or settings.delist.merchant_code_contains,
        max_delist_per_run=int(
            raw.get("max_delist_per_run", settings.delist.max_delist_per_run)
        ),
    )
    if (
        not ds.min_created_after
        and mode not in {"pipeline_relist_prep", "product_operations_code"}
        and not target_product_id
    ):
        return {"errors": ["未配置 delist.min_created_after"], "finished": True}

    account_dict = account.model_dump()

    def _job(dp):
        if mode == "pipeline_relist_prep":
            from pdd_agent.skills.delist.pipeline_relist_prep import process_pipeline_relist_prep_delist

            targets = list(raw.get("targets") or [])
            return process_pipeline_relist_prep_delist(
                dp,
                account_dict,
                targets,
                dry_run=bool(raw.get("dry_run", False)),
                delist_spec_code_search_enabled=bool(raw.get("delist_spec_code_search_enabled")),
            )
        if mode == "inventory_relist":
            from pdd_agent.skills.relist.inventory_goods_list_relist import process_inventory_relist

            targets = list(raw.get("targets") or [])
            return process_inventory_relist(
                dp,
                account_dict,
                targets,
                dry_run=bool(raw.get("dry_run", False)),
                row_strategy=str(raw.get("row_strategy") or "first"),  # type: ignore[arg-type]
            )
        if mode == "product_operations_code":
            from pdd_agent.product_operations.automation import delist_product_by_code

            return delist_product_by_code(
                dp,
                account_dict,
                product_code=target_merchant_code,
                dry_run=bool(raw.get("dry_run", False)),
            )
        if target_product_id:
            return process_single_product_delist(
                dp,
                account_dict,
                product_id=target_product_id,
                mapping_id=target_mapping_id,
                dry_run=bool(raw.get("dry_run", False)),
            )
        return process_account_delist(dp, account_dict, ds)

    try:
        stats = await run_browser_job_async(settings, account, _job)
        if mode == "pipeline_relist_prep":
            if stats.get("delist_skipped"):
                return {
                    "phase": "delist_skipped",
                    "delist_skipped": True,
                    "results": stats.get("results") or [],
                    "warnings": list(stats.get("warnings") or []),
                    "skip_reason": str(stats.get("skip_reason") or ""),
                    "finished": True,
                }
            if stats.get("errors"):
                fatal = [str(e) for e in (stats.get("errors") or []) if str(e).strip()]
                return {
                    "phase": "delist_done",
                    "results": stats.get("results") or [],
                    "warnings": [*list(stats.get("warnings") or []), *fatal],
                    "delist_issues": fatal,
                    "finished": True,
                }
            return {
                "phase": "delist_done",
                "results": stats.get("results") or [],
                "warnings": list(stats.get("warnings") or []),
                "finished": True,
            }
        if mode == "inventory_relist":
            if stats.get("errors"):
                fatal = [str(e) for e in (stats.get("errors") or []) if str(e).strip()]
                return {
                    "phase": "relist_done",
                    "results": stats.get("results") or [],
                    "warnings": [*list(stats.get("warnings") or []), *fatal],
                    "relist_issues": fatal,
                    "finished": True,
                }
            return {
                "phase": "relist_done",
                "results": stats.get("results") or [],
                "warnings": list(stats.get("warnings") or []),
                "finished": True,
            }
        if stats.get("error"):
            return {"errors": [stats["error"]], "results": [stats], "finished": True}
        return {"phase": "delist_done", "results": [stats], "finished": True}
    except Exception as exc:
        logger.exception("delist failed")
        if mode == "pipeline_relist_prep":
            return {
                "phase": "delist_done",
                "results": [],
                "warnings": [str(exc)],
                "delist_issues": [str(exc)],
                "finished": True,
            }
        if mode == "inventory_relist":
            return {
                "phase": "relist_done",
                "results": [],
                "warnings": [str(exc)],
                "relist_issues": [str(exc)],
                "finished": True,
            }
        return {"errors": [str(exc)], "finished": True}


def build_delist_graph():
    graph = StateGraph(DelistState)
    graph.add_node("delist", delist_browser_node)
    graph.set_entry_point("delist")
    graph.add_edge("delist", END)
    return graph.compile()
