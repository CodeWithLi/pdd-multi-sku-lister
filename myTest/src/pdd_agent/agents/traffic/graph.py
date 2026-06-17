"""Traffic Agent — 推广投流自动化。"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from pdd_agent.agents.state import TrafficState
from pdd_agent.browser.sync_job import run_browser_job_async
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_account_config
from pdd_agent.skills.traffic.promotion_create import open_product_promotion_create
from pdd_agent.skills.traffic.promotion_report_scrape import scrape_stable_cost_promotion_report

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


async def promotion_report_scrape_node(state: TrafficState) -> dict:
    """推广概况 → 查看全部推广 → 稳定成本推广 → 昨日数据抓取。"""
    settings = load_yaml_settings()
    account_id = state["account_id"]
    account = get_account_config(settings, account_id)
    if not account:
        return {"errors": [f"unknown account: {account_id}"], "finished": True}

    def _job(dp):
        return scrape_stable_cost_promotion_report(dp, account_id, account=account)

    try:
        result = await run_browser_job_async(settings, account, _job)
        if result.get("status") != "success":
            return {
                "phase": "traffic_failed",
                "results": [result],
                "errors": [result.get("message") or result.get("error") or "promotion report scrape failed"],
                "finished": True,
            }
        logger.info("[%s] promotion report scraped rows=%s", account_id, result.get("total"))
        return {
            "phase": "traffic_report_ready",
            "results": [result],
            "finished": True,
        }
    except Exception as exc:
        logger.exception("promotion report scrape failed")
        return {"errors": [str(exc)], "finished": True}


def _route_traffic_entry(state: TrafficState) -> str:
    traffic_type = str(state.get("traffic_type") or "promotion_create")
    if traffic_type == "promotion_report_scrape":
        return "promotion_report_scrape"
    return "promotion_create"


def build_traffic_graph():
    graph = StateGraph(TrafficState)
    graph.add_node("promotion_create", promotion_create_node)
    graph.add_node("promotion_report_scrape", promotion_report_scrape_node)
    graph.set_conditional_entry_point(
        _route_traffic_entry,
        {
            "promotion_create": "promotion_create",
            "promotion_report_scrape": "promotion_report_scrape",
        },
    )
    graph.add_edge("promotion_create", END)
    graph.add_edge("promotion_report_scrape", END)
    return graph.compile()
