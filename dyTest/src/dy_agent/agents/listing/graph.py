"""
Listing Agent — LangGraph 上架子图。

    preflight ──(无有效单元 / dry_run)──→ report → END
         │
         └──(有 valid_units 且非 dry_run)──→ browser → END
"""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, StateGraph

from dy_agent.agents.state import ListingState
from dy_agent.browser.sync_job import run_browser_job_async
from dy_agent.core.config import get_account, load_yaml_settings
from dy_agent.core.logging import get_logger
from dy_agent.skills.listing.preflight import run_preflight
from dy_agent.skills.listing.upload import run_listing_uploads

logger = get_logger(__name__)


async def preflight_node(state: ListingState) -> dict:
    settings = load_yaml_settings()
    codes = state.get("product_codes") or []
    assets_root: Path | None = None
    raw_root = str(state.get("assets_root") or "").strip()
    if raw_root:
        assets_root = Path(raw_root)

    report = run_preflight(codes, settings, assets_root=assets_root)
    logger.info(
        "preflight: units=%s valid=%s errors=%s",
        len(report.units),
        len(report.valid_units),
        sum(1 for i in report.issues if i.level == "error"),
    )
    return {
        "preflight": report,
        "units": report.valid_units,
        "phase": "preflight",
    }


async def browser_listing_node(state: ListingState) -> dict:
    if state.get("dry_run"):
        return {"phase": "dry_run_skip_browser", "finished": True}

    settings = load_yaml_settings()
    account_id = state["account_id"]
    account = get_account(settings, account_id)
    if not account:
        return {"errors": [f"unknown account: {account_id}"], "finished": True}

    units = state.get("units") or []
    if not units:
        return {"errors": ["no valid listing units"], "finished": True}

    category = state.get("category_keyword") or settings.listing.category_keyword
    defaults = settings.multi_spec.defaults
    run_id = str(state.get("run_id") or "")
    listing_cfg = settings.listing

    def _job(dp):
        return run_listing_uploads(
            dp,
            account_id,
            units,
            category_keyword=category,
            title_mode=settings.listing.title_mode,
            defaults=defaults,
            run_id=run_id,
            slot_alignment_test=bool(state.get("slot_alignment_test", listing_cfg.slot_alignment_test)),
            spec_fill_verify_test=bool(state.get("spec_fill_verify_test", listing_cfg.spec_fill_verify_test)),
            primary_style_first_test=bool(
                state.get("primary_style_first_test", listing_cfg.primary_style_first_test)
            ),
            category_next_burst_demo=bool(
                state.get("category_next_burst_demo", listing_cfg.category_next_burst_demo)
            ),
            accessory_cost_pricing=bool(
                state.get("accessory_cost_pricing", listing_cfg.accessory_cost_pricing)
            ),
            accessory_tiered_float=bool(
                state.get("accessory_tiered_float", listing_cfg.accessory_tiered_float)
            ),
        )

    try:
        results = await run_browser_job_async(settings, account, _job)
        listed = sum(
            1 for r in results if r.get("status") in {"success", "listed", "step1_done"}
        )
        failed = [r for r in results if r.get("status") == "failed"]
        logger.info("[%s] listing done: %s/%s", account_id, listed, len(results))
        out: dict = {"phase": "listing_done", "results": results, "finished": True}
        if failed and listed == 0:
            out["errors"] = [str(r.get("message") or r.get("listing_label")) for r in failed]
        return out
    except Exception as exc:
        logger.exception("browser listing failed")
        return {"errors": [str(exc)], "finished": True}


def should_continue_after_preflight(state: ListingState) -> str:
    if state.get("dry_run"):
        return "report"
    preflight = state.get("preflight")
    if preflight and preflight.valid_units:
        return "browser"
    return "report"


async def report_node(state: ListingState) -> dict:
    units = state.get("units") or []
    lines = [f"- {u.listing_label}: {len(u.skus)} SKU" for u in units]
    msg = "\n".join(lines) if lines else "no valid units"
    logger.info("listing report:\n%s", msg)

    preflight = state.get("preflight")
    errors: list[str] = []
    if preflight and not preflight.ok:
        seen: set[str] = set()
        for issue in preflight.issues:
            if issue.level != "error":
                continue
            label = str(issue.listing_label or issue.message or "").strip()
            if label and label not in seen:
                seen.add(label)
                errors.append(label)
    if not units and not errors:
        errors = ["no valid listing units"]

    result: dict = {"phase": "report", "finished": True, "results": [{"summary": msg}]}
    if errors:
        result["errors"] = errors
    if preflight is not None:
        result["preflight"] = preflight
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
