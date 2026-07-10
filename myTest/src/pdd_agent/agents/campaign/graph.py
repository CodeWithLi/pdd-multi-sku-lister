"""Campaign Agent — 活动工具自动化。"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from pdd_agent.agents.state import CampaignState
from pdd_agent.browser.sync_job import run_browser_job_async
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_account_config
from pdd_agent.skills.campaign.limited_time import setup_limited_time_campaign
from pdd_agent.skills.campaign.marketing_activity_register_bridge import (
    register_marketing_activity_guarded,
    search_marketing_activity_guarded,
)

logger = get_logger(__name__)


async def limited_time_setup_node(state: CampaignState) -> dict:
    """打开限时限量购创建页，完成设置并提交创建。"""
    settings = load_yaml_settings()
    account_id = state["account_id"]
    pdd_product_ids = state.get("pdd_product_ids") or []
    published_mapping_ids = state.get("published_mapping_ids") or []
    account = get_account_config(settings, account_id)
    if not account:
        return {"errors": [f"unknown account: {account_id}"], "finished": True}

    def _job(dp):
        return setup_limited_time_campaign(
            dp,
            account_id,
            pdd_product_ids=pdd_product_ids,
            published_mapping_ids=published_mapping_ids,
            account=account,
        )

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


async def marketing_activity_search_node(state: CampaignState) -> dict:
    """打开营销活动大厅，按活动 ID 搜索。"""
    settings = load_yaml_settings()
    account_id = state["account_id"]
    activity_id = str(state.get("marketing_activity_id") or "").strip()
    account = get_account_config(settings, account_id)
    if not account:
        return {"errors": [f"unknown account: {account_id}"], "finished": True}
    if not activity_id:
        return {"errors": ["marketing_activity_id is required"], "finished": True}

    def _job(dp):
        return search_marketing_activity_guarded(dp, account_id, activity_id, account=account)

    try:
        result = await run_browser_job_async(settings, account, _job)
        if result.get("status") != "success":
            return {
                "phase": "campaign_failed",
                "results": [result],
                "errors": [result.get("error") or "marketing activity search failed"],
                "finished": True,
            }
        logger.info("[%s] marketing activity search done id=%s", account_id, activity_id)
        return {
            "phase": "campaign_ready",
            "results": [result],
            "finished": True,
        }
    except Exception as exc:
        logger.exception("marketing activity search failed")
        return {"errors": [str(exc)], "finished": True}


async def marketing_activity_register_node(state: CampaignState) -> dict:
    """搜索活动并完成去报名 → 立即报名 → 弹窗选品。"""
    settings = load_yaml_settings()
    account_id = state["account_id"]
    activity_id = str(state.get("marketing_activity_id") or "").strip()
    pdd_product_ids = state.get("pdd_product_ids") or []
    account = get_account_config(settings, account_id)
    if not account:
        return {"errors": [f"unknown account: {account_id}"], "finished": True}
    if not activity_id:
        return {"errors": ["marketing_activity_id is required"], "finished": True}
    if not pdd_product_ids:
        return {"errors": ["pdd_product_ids is required"], "finished": True}

    def _job(dp):
        return register_marketing_activity_guarded(
            dp,
            account_id,
            activity_id,
            pdd_product_ids=pdd_product_ids,
            account=account,
        )

    try:
        result = await run_browser_job_async(settings, account, _job)
        if result.get("status") != "success":
            logger.warning(
                "[%s] marketing activity register failed step=%s error=%s url=%s",
                account_id,
                result.get("step"),
                result.get("error") or result.get("message"),
                result.get("current_url"),
            )
            print(
                f"[{account_id}] 活动报名失败: step={result.get('step')} "
                f"error={result.get('error') or result.get('message')} "
                f"url={result.get('current_url')}",
                flush=True,
            )
            return {
                "phase": "campaign_failed",
                "results": [result],
                "errors": [
                    result.get("message")
                    or result.get("error")
                    or "marketing activity register failed"
                ],
                "finished": True,
            }
        logger.info("[%s] marketing activity register done id=%s", account_id, activity_id)
        return {
            "phase": "campaign_ready",
            "results": [result],
            "finished": True,
        }
    except Exception as exc:
        logger.exception("marketing activity register failed")
        return {"errors": [str(exc)], "finished": True}


def _route_campaign_entry(state: CampaignState) -> str:
    campaign_type = str(state.get("campaign_type") or "limited_time_setup")
    if campaign_type == "marketing_activity_register":
        return "marketing_activity_register"
    if campaign_type == "marketing_activity_search":
        return "marketing_activity_search"
    return "limited_time_setup"


def build_campaign_graph():
    graph = StateGraph(CampaignState)
    graph.add_node("limited_time_setup", limited_time_setup_node)
    graph.add_node("marketing_activity_search", marketing_activity_search_node)
    graph.add_node("marketing_activity_register", marketing_activity_register_node)
    graph.set_conditional_entry_point(
        _route_campaign_entry,
        {
            "limited_time_setup": "limited_time_setup",
            "marketing_activity_search": "marketing_activity_search",
            "marketing_activity_register": "marketing_activity_register",
        },
    )
    graph.add_edge("limited_time_setup", END)
    graph.add_edge("marketing_activity_search", END)
    graph.add_edge("marketing_activity_register", END)
    return graph.compile()
