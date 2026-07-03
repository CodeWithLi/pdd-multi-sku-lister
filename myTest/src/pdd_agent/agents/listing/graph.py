"""
Listing Agent — LangGraph 上架子图。

    preflight ──(无有效单元 / dry_run)──→ report → END
         │
         └──(有 valid_units 且非 dry_run)──→ browser → END

单套 preflight/上架失败只记日志，不阻断其余套图；手动取消除外。
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from pdd_agent.agents.state import ListingState
from pdd_agent.browser.sync_job import run_browser_job_async
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_account_config
from pdd_agent.skills.listing.preflight import run_preflight

from pdd_agent.domain.models import PreflightIssue
from pdd_agent.domain.listing_errors import ListingErrorCode
from pdd_agent.skills.listing.upload import run_listing_uploads

logger = get_logger(__name__)


async def preflight_node(state: ListingState) -> dict:
    from pathlib import Path

    settings = load_yaml_settings()
    codes = state.get("product_codes") or []
    assets_root: Path | None = None
    raw_root = str(state.get("assets_root") or "").strip()
    if raw_root:
        assets_root = Path(raw_root)
    try:
        from pdd_agent.integrations.feishu.listing_feishu_catalog import collect_merchant_codes_from_selectors
        from pdd_agent.integrations.feishu.listing_feishu_snapshot import warm_listing_feishu_snapshot
        from pdd_agent.skills.listing.catalog import collect_feishu_catalog_codes_for_targets

        warm_codes = list(
            dict.fromkeys(
                [
                    *collect_merchant_codes_from_selectors(codes),
                    *(collect_feishu_catalog_codes_for_targets(codes, assets_root) if assets_root and codes else []),
                ]
            )
        )
        if warm_codes:
            warm_listing_feishu_snapshot(warm_codes)
    except Exception:
        logger.exception("warm listing feishu snapshot before preflight failed")
    report = run_preflight(
        codes,
        settings,
        slot_alignment_test=bool(state.get("slot_alignment_test"))
        or bool(state.get("spec_fill_verify_test")),
        assets_root=assets_root,
    )
    try:
        from pdd_agent.integrations.feishu.listing_feishu_catalog import collect_merchant_codes_from_selectors
        from pdd_agent.integrations.feishu.listing_feishu_snapshot import warm_listing_feishu_snapshot
        from pdd_agent.integrations.feishu.pdd_product_catalog_sync import _collect_catalog_codes

        warm_listing_feishu_snapshot(
            _collect_catalog_codes(
                units=report.units,
                extra_codes=collect_merchant_codes_from_selectors(codes),
            )
        )
    except Exception:
        logger.exception("warm listing feishu snapshot after preflight failed")
    run_id = str(state.get("run_id") or "")
    account_id = str(state.get("account_id") or "")
    if account_id:
        try:
            from pdd_agent.integrations.feishu.config import load_feishu_config
            from pdd_agent.integrations.feishu.pdd_product_catalog_sync import (
                diagnose_feishu_listing_catalog_issues,
            )

            feishu_cfg = load_feishu_config()
            catalog_issues = diagnose_feishu_listing_catalog_issues(
                units=report.units,
                product_codes=codes,
                config=feishu_cfg,
            )
            from pdd_agent.domain.listing_errors import ListingErrors
            from pdd_agent.integrations.feishu.pdd_upload_sync import _format_brief_listing_failure_reason

            for catalog_issue in catalog_issues:
                detail_rows = list(catalog_issue.details)
                if not detail_rows:
                    report.issues.append(
                        PreflightIssue(
                            level="error",
                            message=catalog_issue.listing_label,
                            listing_label=catalog_issue.listing_label,
                            reason_code="feishu_product_catalog_missing",
                        )
                    )
                    continue
                lines: list[str] = []
                seen_lines: set[str] = set()
                for detail in detail_rows:
                    brief = _format_brief_listing_failure_reason(
                        listing_label=catalog_issue.listing_label,
                        reason_code=detail.reason_code,
                        message=detail.message,
                        merchant_code=detail.code or catalog_issue.merchant_code,
                    )
                    if brief and brief not in seen_lines:
                        seen_lines.add(brief)
                        lines.append(brief)
                combined = ListingErrors.format_numbered(lines)
                report.issues.append(
                    PreflightIssue(
                        level="error",
                        message=combined or detail_rows[0].message,
                        listing_label=catalog_issue.listing_label,
                        reason_code=(
                            detail_rows[0].reason_code
                            if len(detail_rows) == 1
                            else ListingErrorCode.FEISHU_PRODUCT_CATALOG_MISSING
                        ),
                    )
                )
        except Exception:
            logger.exception("check feishu product catalog missing failed")
    if run_id:
        from pdd_agent.api.services.listing_failure_log import record_preflight_issue

        for issue in report.issues:
            if issue.level == "error":
                record_preflight_issue(
                    source_run_id=run_id,
                    account_id=account_id,
                    issue=issue,
                )
        try:
            from pdd_agent.storage import TaskRunStore

            TaskRunStore().merge_run_result(
                run_id,
                {"preflight": report.model_dump(mode="json")},
            )
        except Exception:
            logger.exception("persist listing preflight snapshot failed run_id=%s", run_id)
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
    slot_alignment_test = bool(state.get("slot_alignment_test"))
    spec_fill_verify_test = bool(state.get("spec_fill_verify_test"))
    primary_style_first_test = bool(state.get("primary_style_first_test"))
    category_next_burst_demo = bool(state.get("category_next_burst_demo", True))

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
            slot_alignment_test=slot_alignment_test,
            spec_fill_verify_test=spec_fill_verify_test,
            primary_style_first_test=primary_style_first_test,
            category_next_burst_demo=category_next_burst_demo,
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
    result = {"phase": "report", "finished": True, "results": [{"summary": msg}]}
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
