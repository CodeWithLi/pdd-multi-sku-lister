"""多规格填表流水线（规格名解析 + 抖店「创建类型」填表）。"""

from __future__ import annotations

from playwright.sync_api import Page

from dy_agent.domain.models import ListingUnit, PreflightIssue
from dy_agent.skills.listing.listing_options import ListingOptions
from dy_agent.skills.listing.publish_spec_dimensions import fill_spec_dimensions_via_create_type
from dy_agent.skills.listing.publish_spec_price_table import fill_unit_price_table
from dy_agent.skills.listing.listing_spec_fill_failure_detail import format_spec_fill_verify_reason
from dy_agent.skills.listing.spec_labels import enrich_listing_unit_specs, ordered_style_names, refresh_unit_spec_code_lists


def prepare_spec_pipeline_flags(options: ListingOptions) -> dict:
    return {
        "slot_alignment_test": options.slot_alignment_test,
        "spec_fill_verify_test": options.spec_fill_verify_test,
        "primary_style_first_test": options.primary_style_first_test,
        "ready": True,
    }


def apply_unit_listing_specs(
    unit: ListingUnit,
    *,
    account_id: str = "",
    allow_ai: bool = True,
    slot_alignment_test: bool = False,
) -> list[str]:
    """解析单元规格展示名（与拼多多相同逻辑）。"""
    enrich_listing_unit_specs(unit, account_id=account_id, allow_ai=allow_ai)
    if not slot_alignment_test:
        return []

    try:
        from dy_agent.skills.listing.slot_alignment import apply_slot_alignment
    except ImportError:
        return [f"[{unit.listing_label}] 槽位对齐尚未接入抖店"]

    result = apply_slot_alignment(unit, account_id=account_id)
    if result.ok:
        refresh_unit_spec_code_lists(unit)
        return []
    return list(result.errors)


def preflight_issues_from_slot_errors(errors: list[str]) -> list[PreflightIssue]:
    return [PreflightIssue(level="error", message=msg, listing_label=_label_from_msg(msg)) for msg in errors]


def _label_from_msg(message: str) -> str:
    text = message.strip()
    if text.startswith("[") and "]" in text:
        return text[1 : text.index("]")]
    return ""


def run_spec_fill_pipeline(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
) -> dict:
    """Step4：解析规格名并按抖店「创建类型」流程填入颜色分类 / 尺寸大小。"""
    spec_errors = apply_unit_listing_specs(
        unit,
        account_id=account_id,
        allow_ai=True,
        slot_alignment_test=options.slot_alignment_test,
    )
    if spec_errors:
        raise RuntimeError(f"[{account_id}] [{unit.listing_label}] 规格预处理失败: {'; '.join(spec_errors)}")

    style_names = ordered_style_names(unit)
    size_names = list(unit.model_codes)
    if not style_names:
        raise RuntimeError(f"[{account_id}] [{unit.listing_label}] 无款式（颜色分类）可填")

    from dy_agent.skills.listing.publish_spec_dimensions import _log as spec_log

    spec_log(
        account_id,
        unit.listing_label,
        f"规格预处理完成：颜色分类={style_names}；尺寸大小={size_names}",
    )

    fill_result = fill_spec_dimensions_via_create_type(
        page,
        account_id,
        unit.listing_label,
        style_names,
        size_names,
    )
    return {
        "style_names": style_names,
        "size_names": size_names,
        **fill_result,
    }


def run_spec_price_fill_pipeline(
    page: Page,
    account_id: str,
    unit: ListingUnit,
    options: ListingOptions,
    *,
    defaults: dict[str, str] | None = None,
) -> dict:
    """Step5：价格 / 现货库存 / 商家编码填表（可选规格填表校验）。"""
    from dy_agent.skills.listing.publish_spec_price_table import ensure_price_table_rows_ready

    style_names = ordered_style_names(unit)
    size_names = list(unit.model_codes)
    if not unit.skus:
        raise RuntimeError(f"[{account_id}] [{unit.listing_label}] 无 SKU 可填价格表")

    ensure_price_table_rows_ready(
        page,
        account_id,
        unit.listing_label,
        expected=len(unit.skus),
        style_names=style_names,
        size_names=size_names,
    )

    stats = fill_unit_price_table(
        page,
        account_id,
        unit,
        style_names=style_names,
        size_names=size_names,
        defaults=defaults,
        verify=bool(options.spec_fill_verify_test),
    )
    if options.spec_fill_verify_test and not stats.get("verify_passed"):
        raise RuntimeError(
            f"[{account_id}] [{unit.listing_label}] 规格填表校验失败: "
            f"{format_spec_fill_verify_reason(stats)}"
        )
    if not options.spec_fill_verify_test and stats.get("failed_items"):
        failed = stats.get("failed_items") or []
        raise RuntimeError(
            f"[{account_id}] [{unit.listing_label}] 价格表填写失败 {len(failed)} 项"
        )

    return {
        "style_names": style_names,
        "size_names": size_names,
        **stats,
    }
