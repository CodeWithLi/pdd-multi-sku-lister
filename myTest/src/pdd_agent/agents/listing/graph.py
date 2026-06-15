"""
Listing Agent — LangGraph 上架子图。

    preflight ──(校验失败/dry_run)──→ report → END
         │
         └──(校验通过且非 dry_run)──→ browser → END
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from pdd_agent.agents.state import ListingState
from pdd_agent.browser.sync_job import run_browser_job_async
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_account_config
from pdd_agent.skills.listing.preflight import run_preflight
from pdd_agent.skills.listing.upload import run_listing_uploads

logger = get_logger(__name__)


async def preflight_node(state: ListingState) -> dict:
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


async def browser_listing_node(state: ListingState) -> dict:
    """登录 + 多规格上架（Playwright 同步线程）。"""
    if state.get("dry_run"):
        return {"phase": "dry_run_skip_browser", "finished": True}

    settings = load_yaml_settings()
    account_id = state["account_id"]
    account = get_account_config(settings, account_id)
    if not account:
        return {"errors": [f"unknown account: {account_id}"], "finished": True}

    units = state.get("units") or []
    retry_image_set = (state.get("retry_item") or {}).get("image_set", "")
    retry_product_code = (state.get("retry_item") or {}).get("product_code", "")
    if retry_product_code:
        units = [
            unit
            for unit in units
            if unit.product_code == retry_product_code
            and (not retry_image_set or unit.image_set == retry_image_set)
        ]
    if not units:
        run_id = str(state.get("run_id") or "")
        if run_id:
            from pdd_agent.api.services.listing_failure_log import record_listing_failure_detail

            record_listing_failure_detail(
                source_run_id=run_id,
                account_id=account_id,
                listing_label="",
                phase="listing",
                step="browser_start",
                severity="error",
                reason_code="no_valid_units",
                message="无有效上架单元（preflight 后 units 为空）",
            )
        return {"errors": ["no valid listing units"], "finished": True}

    category = state.get("category_keyword") or settings.listing.category_keyword
    platform_listing_code = (state.get("platform_listing_code") or "").strip()
    if platform_listing_code:
        if len(units) > 1:
            return {
                "errors": ["platform_listing_code requires exactly one listing unit"],
                "finished": True,
            }
    defaults = settings.multi_spec.defaults
    run_id = str(state.get("run_id") or "")

    def _job(dp):
        return run_listing_uploads(
            dp,
            account_id,
            units,
            category_keyword=category,
            title_mode=settings.listing.title_mode,
            platform_listing_code=platform_listing_code,
            defaults=defaults,
            run_id=run_id,
        )

    try:
        results = await run_browser_job_async(settings, account, _job)
        listed = sum(1 for r in results if r.get("status") in {"success", "listed"})
        logger.info("[%s] listing done: %s/%s listed", account_id, listed, len(results))
        return {
            "phase": "listing_done",
            "results": results,
            "finished": True,
        }
    except Exception as exc:
        logger.exception("browser listing failed")
        return {"errors": [str(exc)], "finished": True}


def should_continue_after_preflight(state: ListingState) -> str:
    preflight = state.get("preflight")
    if not preflight or not preflight.ok:
        return "report"
    if state.get("dry_run"):
        return "report"
    return "browser"


async def report_node(state: ListingState) -> dict:
    units = state.get("units") or []
    lines = [f"- {u.listing_label}: {len(u.skus)} SKU" for u in units]
    msg = "\n".join(lines) if lines else "no valid units"
    logger.info("listing report:\n%s", msg)
    preflight = state.get("preflight")
    errors: list[str] = []
    if preflight and not preflight.ok:
        errors = [i.message for i in preflight.issues if i.level == "error"]
    if not units and not errors:
        errors = ["no valid listing units"]
    result = {"phase": "report", "finished": True, "results": [{"summary": msg}]}
    if errors:
        result["errors"] = errors
    return result


def build_listing_graph():
    graph = StateGraph(ListingState)
    graph.add_node("preflight", preflight_node)
    graph.add_node("browser", browser_listing_node)
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
