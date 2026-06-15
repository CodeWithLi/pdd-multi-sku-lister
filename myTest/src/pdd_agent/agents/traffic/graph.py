"""Traffic Agent — 推广投流自动化。"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from pdd_agent.agents.state import TrafficState
from pdd_agent.browser.sync_job import run_browser_job_async
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_account_config
from pdd_agent.skills.traffic.promotion_create import open_product_promotion_create

logger = get_logger(__name__)


async def promotion_create_node(state: TrafficState) -> dict:
    """推广概况 → 商品推广 → 新建推广。"""
    settings = load_yaml_settings()
    account_id = state["account_id"]
    pdd_product_ids = state.get("pdd_product_ids") or []
    account = get_account_config(settings, account_id)
    if not account:
        return {"errors": [f"unknown account: {account_id}"], "finished": True}

    def _job(dp):
        return open_product_promotion_create(
            dp,
            account_id,
            pdd_product_ids=pdd_product_ids,
            account=account,
        )

    try:
        result = await run_browser_job_async(settings, account, _job)
        if result.get("status") != "success":
            return {
                "phase": "traffic_failed",
                "results": [result],
                "errors": [result.get("error") or "promotion create navigation failed"],
                "finished": True,
            }
        logger.info("[%s] promotion create page opened", account_id)
        return {
            "phase": "traffic_ready",
            "results": [result],
            "finished": True,
        }
    except Exception as exc:
        logger.exception("promotion create navigation failed")
        return {"errors": [str(exc)], "finished": True}


def _route_traffic_entry(state: TrafficState) -> str:
    traffic_type = str(state.get("traffic_type") or "promotion_create")
    if traffic_type == "promotion_create":
        return "promotion_create"
    return "promotion_create"


def build_traffic_graph():
    graph = StateGraph(TrafficState)
    graph.add_node("promotion_create", promotion_create_node)
    graph.set_conditional_entry_point(
        _route_traffic_entry,
        {"promotion_create": "promotion_create"},
    )
    graph.add_edge("promotion_create", END)
    return graph.compile()
