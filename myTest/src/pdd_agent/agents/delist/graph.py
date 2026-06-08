"""Delist Agent — 登录后扫描在售商品并下架。"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from pdd_agent.agents.state import DelistState
from pdd_agent.browser.sync_job import run_browser_job_async
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_account_config
from pdd_agent.skills.delist.automation import DelistSettings, process_account_delist

logger = get_logger(__name__)


async def delist_browser_node(state: DelistState) -> dict:
    settings = load_yaml_settings()
    account_id = state["account_id"]
    account = get_account_config(settings, account_id)
    if not account:
        return {"errors": [f"unknown account: {account_id}"], "finished": True}

    raw = state.get("delist_params") or {}
    ds = DelistSettings(
        min_created_after=raw.get("min_created_after") or settings.delist.min_created_after,
        dry_run=raw.get("dry_run", settings.delist.dry_run),
        merchant_code_contains=raw.get("merchant_code_contains")
        or settings.delist.merchant_code_contains,
        max_delist_per_run=int(
            raw.get("max_delist_per_run", settings.delist.max_delist_per_run)
        ),
    )
    if not ds.min_created_after:
        return {"errors": ["未配置 delist.min_created_after"], "finished": True}

    account_dict = account.model_dump()

    def _job(dp):
        return process_account_delist(dp, account_dict, ds)

    try:
        stats = await run_browser_job_async(settings, account, _job)
        if stats.get("error"):
            return {"errors": [stats["error"]], "results": [stats], "finished": True}
        return {"phase": "delist_done", "results": [stats], "finished": True}
    except Exception as exc:
        logger.exception("delist failed")
        return {"errors": [str(exc)], "finished": True}


def build_delist_graph():
    graph = StateGraph(DelistState)
    graph.add_node("delist", delist_browser_node)
    graph.set_entry_point("delist")
    graph.add_edge("delist", END)
    return graph.compile()
