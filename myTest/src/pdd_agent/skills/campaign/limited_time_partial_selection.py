"""
限时限量购 — 选品「部分成功继续」策略。

与 limited_time.py 主流程解耦：当弹窗内部分商品 ID 搜不到/勾不上时，
对已勾选成功的商品继续确认选择并进入后续步骤；搜不到的 ID 跳过。
"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_published_products_by_pdd_product_ids

logger = get_logger(__name__)

PARTIAL_ROWS_FAILURE_STEP = "select_product_rows"
PARTIAL_SUCCESS_STEP = "product_selected_partial"


def _partial_log(account_id: str, step_label: str, message: str, **extra: Any) -> None:
    prefix = f"[{account_id}] [限时限量购][部分选品][{step_label}]"
    parts = [f"{key}={value}" for key, value in extra.items() if value is not None and value != ""]
    line = f"{prefix} {message}"
    if parts:
        line = f"{line} | {' '.join(parts)}"
    logger.info(line)
    print(line, flush=True)


def is_partial_rows_failure(result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict):
        return False
    if str(result.get("status") or "") != "failed":
        return False
    if str(result.get("step") or "") != PARTIAL_ROWS_FAILURE_STEP:
        return False
    return bool(result.get("selected_ids"))


def continue_product_selection_after_partial_rows(
    page: DpPage,
    account_id: str,
    *,
    selected_ids: list[str],
    missing_ids: list[str],
    target_ids: list[str],
    batches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """在弹窗内已有部分勾选时，继续确认选择并校验活动页已选商品（仅校验成功子集）。"""
    from pdd_agent.skills.campaign.limited_time import (
        ACTIVITY_CREATE_URL_PARTS,
        _activity_has_selected_products,
        _confirm_product_selection,
        _dismiss_product_modal_after_confirm,
        _ensure_page_binding,
        _wait_activity_selected_products,
        _wait_activity_settings,
    )

    selected_ids = list(dict.fromkeys(str(item).strip() for item in selected_ids if str(item).strip()))
    missing_ids = list(dict.fromkeys(str(item).strip() for item in missing_ids if str(item).strip()))
    target_ids = list(dict.fromkeys(str(item).strip() for item in target_ids if str(item).strip()))
    batches = list(batches or [])

    _partial_log(
        account_id,
        "继续",
        "部分商品已勾选，尝试确认选择",
        selected_ids=selected_ids,
        missing_ids=missing_ids,
    )

    confirm = _confirm_product_selection(page, account_id)
    if not confirm.get("clicked"):
        return {
            "status": "failed",
            "step": "confirm_product_selection",
            "error": confirm.get("reason") or "部分选品后无法点击确认选择",
            "partial_success": False,
            "target_ids": target_ids,
            "selected_ids": selected_ids,
            "missing_ids": missing_ids,
            "batches": batches,
            "confirm": confirm,
        }

    modal_dismissal = _dismiss_product_modal_after_confirm(
        page,
        account_id,
        selected_ids,
        timeout=24,
    )
    closed = bool(modal_dismissal.get("closed"))
    time.sleep(10)
    activity_page_ready = _ensure_page_binding(
        page,
        preferred_url_parts=ACTIVITY_CREATE_URL_PARTS,
        timeout=15,
    )
    if activity_page_ready:
        _wait_activity_settings(page, account_id, timeout=6)

    activity_selected = _wait_activity_selected_products(page, selected_ids, timeout=15)
    visible_selected_ids = [str(item) for item in activity_selected.get("ids") or []]
    selected_visible_on_page = all(item in visible_selected_ids for item in selected_ids)
    selected_count_done = _activity_has_selected_products(
        activity_selected,
        selected_ids,
        allow_count_fallback=True,
    )
    selected_done = selected_visible_on_page or selected_count_done
    product_selection_done = closed and selected_done

    if not closed:
        error = "部分选品确认后选择商品弹窗未关闭"
    elif not selected_done:
        error = "部分选品确认后未在活动页看到已选商品"
    else:
        error = ""

    outcome_status = "success" if product_selection_done else "failed"
    _partial_log(
        account_id,
        "完成" if product_selection_done else "失败",
        "部分选品确认结果",
        status=outcome_status,
        selected_ids=selected_ids,
        missing_ids=missing_ids,
        modal_closed=closed,
        visible_on_page=selected_visible_on_page,
        error=error,
    )

    return {
        "status": outcome_status,
        "step": PARTIAL_SUCCESS_STEP if product_selection_done else "wait_product_modal_closed",
        "partial_success": product_selection_done,
        "partial_skip_reason": (
            f"弹窗内 {len(missing_ids)} 个商品未找到或未勾选，已跳过：{', '.join(missing_ids)}"
            if missing_ids
            else ""
        ),
        "target_ids": target_ids,
        "selected_ids": selected_ids,
        "missing_ids": missing_ids,
        "batches": batches,
        "confirm": confirm,
        "modal_closed": closed,
        "modal_dismissal": modal_dismissal,
        "activity_page_ready": activity_page_ready,
        "activity_selected": activity_selected,
        "selected_visible_on_page": selected_visible_on_page,
        "selected_count_done": selected_count_done,
        "selected_done": selected_done,
        "error": error,
    }


def select_campaign_products_allow_partial(
    page: DpPage,
    account_id: str,
    product_ids: list[str],
) -> dict[str, Any]:
    """调用原选品逻辑；若仅因部分 ID 未勾选失败，则对已勾选商品继续确认并返回成功。"""
    from pdd_agent.skills.campaign.limited_time import _select_campaign_products

    result = _select_campaign_products(page, account_id, product_ids)
    if str(result.get("status") or "") == "success":
        return result
    if not is_partial_rows_failure(result):
        return result

    selected_ids = [str(item).strip() for item in (result.get("selected_ids") or []) if str(item).strip()]
    if not selected_ids:
        return result

    continued = continue_product_selection_after_partial_rows(
        page,
        account_id,
        selected_ids=selected_ids,
        missing_ids=[str(item).strip() for item in (result.get("missing_ids") or []) if str(item).strip()],
        target_ids=[str(item).strip() for item in (result.get("target_ids") or product_ids) if str(item).strip()],
        batches=result.get("batches") if isinstance(result.get("batches"), list) else [],
    )
    continued["partial_from_failure"] = {
        "original_step": result.get("step"),
        "original_error": result.get("error"),
    }
    return continued


def narrow_scope_to_selected_products(
    account_id: str,
    pdd_product_ids: list[str],
    mapping_ids: list[str],
    product_selection: dict[str, Any],
) -> tuple[list[str], list[str], dict[str, Any]]:
    """将后续限时限量购步骤的商品范围收窄为选品成功的 ID。"""
    account_id = str(account_id or "").strip()
    requested_pdd = list(dict.fromkeys(str(item).strip() for item in pdd_product_ids if str(item).strip()))
    requested_mapping = list(dict.fromkeys(str(item).strip() for item in mapping_ids if str(item).strip()))

    if str(product_selection.get("status") or "") != "success":
        return requested_pdd, requested_mapping, {"scope_applied": False}

    selected_pdd = list(
        dict.fromkeys(str(item).strip() for item in (product_selection.get("selected_ids") or []) if str(item).strip())
    )
    if not selected_pdd:
        selected_pdd = requested_pdd

    if selected_pdd == requested_pdd:
        return requested_pdd, requested_mapping, {
            "scope_applied": False,
            "selected_pdd_product_ids": selected_pdd,
        }

    rows = get_published_products_by_pdd_product_ids(
        account_id=account_id,
        pdd_product_ids=selected_pdd,
    )
    allowed_mapping = {str(row.mapping_id or "").strip() for row in rows if str(row.mapping_id or "").strip()}
    narrowed_mapping = [item for item in requested_mapping if item in allowed_mapping]
    if not narrowed_mapping and allowed_mapping:
        narrowed_mapping = list(dict.fromkeys(allowed_mapping))

    missing_ids = list(product_selection.get("missing_ids") or [])
    meta = {
        "scope_applied": True,
        "partial_success": bool(product_selection.get("partial_success")),
        "requested_pdd_product_ids": requested_pdd,
        "selected_pdd_product_ids": selected_pdd,
        "skipped_pdd_product_ids": missing_ids,
        "partial_skip_reason": product_selection.get("partial_skip_reason") or "",
    }
    return selected_pdd, narrowed_mapping, meta
