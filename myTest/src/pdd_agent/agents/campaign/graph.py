"""Campaign Agent — 活动工具自动化。"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from pdd_agent.agents.state import CampaignState
from pdd_agent.browser.sync_job import run_browser_job_async
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_account_config
from pdd_agent.skills.campaign.limited_time import setup_limited_time_campaign

logger = get_logger(__name__)


async def limited_time_setup_node(state: CampaignState) -> dict:
    """打开限时限量购创建页，并取消同步设置惊喜优惠。"""
    settings = load_yaml_settings()
    account_id = state["account_id"]
    account = get_account_config(settings, account_id)
    if not account:
        return {"errors": [f"unknown account: {account_id}"], "finished": True}

    def _job(dp):
        return setup_limited_time_campaign(dp, account_id)

    try:
        result = await run_browser_job_async(settings, account, _job)
        if result.get("status") != "success":
            return {
                "phase": "campaign_failed",
                "results": [result],
                "errors": [result.get("error") or "campaign setup failed"],
                "finished": True,
            }
        logger.info("[%s] limited time campaign setup done", account_id)
        return {
            "phase": "campaign_ready",
            "results": [result],
            "finished": True,
        }
    except Exception as exc:
        logger.exception("campaign setup failed")
        return {"errors": [str(exc)], "finished": True}


def build_campaign_graph():
    graph = StateGraph(CampaignState)
    graph.add_node("limited_time_setup", limited_time_setup_node)
    graph.set_entry_point("limited_time_setup")
    graph.add_edge("limited_time_setup", END)
    return graph.compile()
