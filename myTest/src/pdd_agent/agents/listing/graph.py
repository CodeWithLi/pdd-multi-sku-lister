"""
Listing Agent — LangGraph 上架子图。

    preflight ──(校验失败/dry_run)──→ report → END
         │
         └──(校验通过且非 dry_run)──→ browser → END

browser 节点当前仅完成登录；页面上传/填规格见 agents/listing/nodes.py。
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from pdd_agent.agents.state import ListingState
from pdd_agent.browser import BrowserManager, BrowserSession
from pdd_agent.core.config import get_account, load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.skills.listing.preflight import run_preflight

logger = get_logger(__name__)


async def preflight_node(state: ListingState) -> dict:
    """调用 preflight Skill，填充 units 与 preflight 报告。"""
    settings = load_yaml_settings()
    codes = state.get("product_codes") or []
    report = run_preflight(codes, settings)
    logger.info(
        "preflight: units=%s ok=%s errors=%s",
        len(report.units),
        report.ok,
        sum(1 for i in report.issues if i.level == "error"),
    )
    return {
        "preflight": report,
        "units": report.valid_units,
        "phase": "preflight",
    }


async def browser_login_node(state: ListingState) -> dict:
    """启动 Playwright，登录店铺；实际上传步骤待 nodes.py 实现。"""
    if state.get("dry_run"):
        return {"phase": "dry_run_skip_browser", "finished": True}

    settings = load_yaml_settings()
    account_id = state["account_id"]
    account = get_account(settings, account_id)
    if not account:
        return {"errors": [f"unknown account: {account_id}"], "finished": True}

    manager = BrowserManager(settings)
    await manager.start()
    try:
        async with manager.open_context(account_id) as context:
            session = await BrowserSession.open(account, context)
            await session.ensure_login(settings)
            logger.info("[%s] browser ready, upload steps TBD", account_id)
            return {
                "phase": "browser_ready",
                "results": [{"account_id": account_id, "status": "browser_ready"}],
                "finished": True,
            }
    except Exception as exc:
        logger.exception("browser login failed")
        return {"errors": [str(exc)], "finished": True}
    finally:
        await manager.stop()


def should_continue_after_preflight(state: ListingState) -> str:
    """条件边：决定走 browser 还是直接 report。"""
    preflight = state.get("preflight")
    if not preflight or not preflight.ok:
        return "report"
    if state.get("dry_run"):
        return "report"
    return "browser"


async def report_node(state: ListingState) -> dict:
    """输出可上架单元摘要（dry-run 或校验失败时也会进入）。"""
    units = state.get("units") or []
    lines = [f"- {u.listing_label}: {len(u.skus)} SKU" for u in units]
    msg = "\n".join(lines) if lines else "no valid units"
    logger.info("listing report:\n%s", msg)
    return {"phase": "report", "finished": True, "results": [{"summary": msg}]}


def build_listing_graph():
    """编译 Listing 状态图。"""
    graph = StateGraph(ListingState)
    graph.add_node("preflight", preflight_node)
    graph.add_node("browser", browser_login_node)
    graph.add_node("report", report_node)

    graph.set_entry_point("preflight")
    graph.add_conditional_edges(
        "preflight",
        should_continue_after_preflight,
        {"browser": "browser", "report": "report"},
    )
    graph.add_edge("browser", END)
    graph.add_edge("report", END)
    return graph.compile()
