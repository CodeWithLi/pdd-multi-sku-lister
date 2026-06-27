"""整合链路 — 批量精准下架（商品编码筛选 + 逐行校验 + 分页下架）。"""

from __future__ import annotations

from typing import Any

from pdd_agent.browser.shop_display_name import verify_shop_for_account
from pdd_agent.skills.delist.automation import (
    DELIST_MERCHANT_CODE_SEARCH_BATCH_SIZE,
    _log,
    batch_delist_by_verified_checkboxes,
    chunk_merchant_codes_for_search,
    filter_goods_by_merchant_codes,
    merchant_code_matches_expected,
    open_goods_list_on_sale,
    scan_filtered_product_rows_all_pages,
)

SKIP_REASON_FILTER_UNVERIFIED = "filter_verification_failed"
SKIP_REASON_ID_MISMATCH = "product_id_verification_failed"
SKIP_REASON_SET_FILTER_FAILED = "set_merchant_code_filter_failed"
SKIP_REASON_SEARCH_NO_HIT = "merchant_code_search_no_hit"

NON_BLOCKING_DELIST_ITEM_ERRORS = frozenset(
    {
        SKIP_REASON_SET_FILTER_FAILED,
        SKIP_REASON_SEARCH_NO_HIT,
        "product_id_not_found_on_sale",
    }
)


def discover_on_sale_product_ids_by_merchant_code(
    page,
    account_id: str,
    merchant_code: str,
) -> list[str]:
    """兼容旧调用：单编码筛选。"""
    code = str(merchant_code or "").strip()
    if not code:
        return []
    if not open_goods_list_on_sale(page, account_id):
        return []
    if not filter_goods_by_merchant_codes(page, account_id, [code]):
        return []
    return [
        str(item.get("product_id") or "").strip()
        for item in scan_filtered_product_rows_all_pages(page, account_id, merchant_codes=[code])
        if str(item.get("product_id") or "").strip()
    ]


def _verify_scanned_rows_for_merchant_codes(
    scanned_rows: list[dict[str, Any]],
    merchant_codes: list[str],
) -> tuple[list[dict[str, Any]], str]:
    """只保留行内商品编码与目标编码完全一致的行，其余跳过。"""
    expected = {str(code or "").strip() for code in merchant_codes if str(code or "").strip()}
    if not expected:
        return [], "missing_merchant_codes"

    verified: list[dict[str, Any]] = []
    for row in scanned_rows:
        product_id = str(row.get("product_id") or "").strip()
        merchant_code = str(row.get("merchant_code") or "").strip()
        if not product_id:
            continue
        matched = merchant_code_matches_expected(merchant_code, expected)
        if not matched:
            continue
        verified.append({**row, "merchant_code": matched})
    return verified, ""


def _verify_known_product_ids(
    merchant_groups: dict[str, dict[str, Any]],
    discovered_by_code: dict[str, list[str]],
) -> str:
    """
    若本地有记录的商品ID，则扫描结果中必须至少命中一个已知ID。
    防止筛选异常时误下架其它链接。
    """
    for code, group in merchant_groups.items():
        known_ids = [str(pid or "").strip() for pid in (group.get("known_ids") or []) if str(pid or "").strip()]
        if not known_ids:
            continue
        scanned_ids = [str(pid or "").strip() for pid in discovered_by_code.get(code, []) if str(pid or "").strip()]
        if not scanned_ids:
            continue
        if not set(known_ids) & set(scanned_ids):
            return SKIP_REASON_ID_MISMATCH
    return ""


def _verify_scanned_rows_for_product_ids(
    scanned_rows: list[dict[str, Any]],
    expected_ids: list[str],
) -> tuple[list[dict[str, Any]], str]:
    expected = {str(pid or "").strip() for pid in expected_ids if str(pid or "").strip()}
    if not expected:
        return [], "missing_product_ids"

    verified: list[dict[str, Any]] = []
    for row in scanned_rows:
        product_id = str(row.get("product_id") or "").strip()
        if not product_id:
            continue
        if product_id not in expected:
            return [], SKIP_REASON_FILTER_UNVERIFIED
        verified.append(row)
    return verified, ""


def _skip_delist_result(
    *,
    account_id: str,
    skip_reason: str,
    results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reason_labels = {
        SKIP_REASON_FILTER_UNVERIFIED: "商品列表筛选未通过校验（疑似展示全部商品），已跳过下架",
        SKIP_REASON_ID_MISMATCH: "扫描到的商品ID与系统记录不一致，已跳过下架",
        SKIP_REASON_SET_FILTER_FAILED: "商品编码筛选失败，已跳过下架",
    }
    warning = reason_labels.get(skip_reason, "下架校验未通过，已跳过下架")
    _log(account_id, warning)
    return {
        "account_id": account_id,
        "mode": "pipeline_relist_prep",
        "results": list(results or []),
        "errors": [],
        "warnings": [warning],
        "delist_skipped": True,
        "skip_reason": skip_reason,
        "hit": 0,
        "scanned": len(results or []),
    }


def _results_from_batch_delist(
    batch_result: dict[str, object],
    merchant_groups: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """将分页批量下架结果映射为 pipeline 结果行。"""
    results: list[dict[str, Any]] = []
    delisted_by_code: dict[str, list[str]] = {}
    for item in batch_result.get("delisted_items") or []:
        if not isinstance(item, dict):
            continue
        matched = str(item.get("matched_code") or item.get("merchant_code") or "").strip()
        product_id = str(item.get("product_id") or "").strip()
        if matched and product_id:
            delisted_by_code.setdefault(matched, []).append(product_id)

    for code, group in merchant_groups.items():
        mapping_id = str(group.get("mapping_id") or "")
        selector = str(group.get("selector") or "")
        product_ids = list(dict.fromkeys(delisted_by_code.get(code, [])))
        if not product_ids:
            results.append(
                {
                    "mapping_id": mapping_id,
                    "selector": selector,
                    "merchant_code": code,
                    "error": "product_id_not_found_on_sale",
                }
            )
            continue
        for product_id in product_ids:
            results.append(
                {
                    "mapping_id": mapping_id,
                    "selector": selector,
                    "merchant_code": code,
                    "target_product_id": product_id,
                    "status": "delisted",
                }
            )
    return results


def _delist_merchant_code_batch(
    page,
    account_id: str,
    codes: list[str],
    groups: dict[str, dict[str, Any]],
    *,
    dry_run: bool,
    try_spec_code_search: bool = False,
) -> list[dict[str, Any]]:
    """一次搜索本批全部编码（空格分隔），逐行校验编码后下架。"""
    results: list[dict[str, Any]] = []
    if not codes:
        return results

    _log(
        account_id,
        f"商品编码批量搜索（{len(codes)} 个，空格分隔）：{' '.join(codes)[:300]}",
    )

    if not filter_goods_by_merchant_codes(
        page,
        account_id,
        codes,
        try_spec_code_search=try_spec_code_search,
    ):
        for code in codes:
            group = groups.get(code) or {}
            results.append(
                {
                    "mapping_id": str(group.get("mapping_id") or ""),
                    "selector": str(group.get("selector") or ""),
                    "merchant_code": code,
                    "error": SKIP_REASON_SEARCH_NO_HIT,
                }
            )
        return results

    batch_result = batch_delist_by_verified_checkboxes(
        page,
        account_id,
        codes,
        dry_run=dry_run,
    )
    batch_errors = [str(e).strip() for e in (batch_result.get("errors") or []) if str(e).strip()]
    chunk_groups = {code: groups[code] for code in codes if code in groups}
    if batch_errors and int(batch_result.get("total_delisted") or 0) <= 0:
        for code in codes:
            group = groups.get(code) or {}
            results.append(
                {
                    "mapping_id": str(group.get("mapping_id") or ""),
                    "selector": str(group.get("selector") or ""),
                    "merchant_code": code,
                    "error": batch_errors[0],
                }
            )
        return results

    results.extend(_results_from_batch_delist(batch_result, chunk_groups))
    missing = [code for code in codes if code not in set(batch_result.get("found_codes") or [])]
    for code in missing:
        _log(
            account_id,
            f"编码 {code} 本批未命中（请核对拼多多后台「商品编码」是否与文件夹名完全一致）",
        )
    return results


def process_pipeline_relist_prep_delist(
    page,
    account_config: dict,
    targets: list[dict[str, Any]],
    *,
    dry_run: bool = False,
    delist_spec_code_search_enabled: bool = False,
) -> dict[str, Any]:
    """
    按商品编码分批（每批最多 5 个）搜索，逐行校验编码完全一致后下架。
    同编码多链接：编码一致即下架；规格编码搜索由 delist_spec_code_search_enabled 控制。
    """
    account_id = str(account_config.get("account_id") or "")
    login_username = str(account_config.get("username") or "")
    results: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}

    for raw in targets or []:
        if not isinstance(raw, dict):
            continue
        merchant_code = str(raw.get("merchant_code") or "").strip()
        if not merchant_code:
            _log(account_id, "跳过无商品编码的下架目标（仅支持按商品编码下架）")
            continue
        if merchant_code not in groups:
            groups[merchant_code] = {
                "merchant_code": merchant_code,
                "mapping_id": str(raw.get("mapping_id") or "").strip(),
                "selector": str(raw.get("selector") or "").strip(),
            }
        group = groups[merchant_code]
        if not group.get("mapping_id"):
            group["mapping_id"] = str(raw.get("mapping_id") or "").strip()
        if not group.get("selector"):
            group["selector"] = str(raw.get("selector") or "").strip()

    if not groups:
        return {
            "account_id": account_id,
            "mode": "pipeline_relist_prep",
            "results": [],
            "errors": [],
            "hit": 0,
            "scanned": 0,
        }

    _log(
        account_id,
        f"整合链路下架预备开始（本链路仅执行一次，共 {len(groups)} 个商品编码）",
    )

    if not open_goods_list_on_sale(page, account_id):
        err = "打开商品列表失败"
        return {
            "account_id": account_id,
            "mode": "pipeline_relist_prep",
            "results": [],
            "errors": [],
            "warnings": [err],
            "hit": 0,
            "scanned": 0,
        }

    shop_check = verify_shop_for_account(account_id, page, login_username=login_username)
    if not shop_check.ok:
        err = (
            f"店铺校验失败：期望「{shop_check.expected or account_id}」，"
            f"当前页面「{shop_check.actual or '未知'}」({shop_check.error})"
        )
        _log(account_id, err)
        return {
            "account_id": account_id,
            "mode": "pipeline_relist_prep",
            "results": [],
            "errors": [],
            "warnings": [err],
            "hit": 0,
            "scanned": 0,
        }

    code_list = list(groups.keys())
    batches = chunk_merchant_codes_for_search(code_list)
    _log(
        account_id,
        f"下架预备：共 {len(code_list)} 个商品编码，"
        f"每批最多 {DELIST_MERCHANT_CODE_SEARCH_BATCH_SIZE} 个空格分隔搜索（共 {len(batches)} 批）；"
        f"规格编码搜索={'开启' if delist_spec_code_search_enabled else '关闭'}",
    )

    for batch_index, chunk_codes in enumerate(batches, start=1):
        _log(account_id, f"下架批次 {batch_index}/{len(batches)}：{' '.join(chunk_codes)[:300]}")
        chunk_groups = {code: groups[code] for code in chunk_codes}
        results.extend(
            _delist_merchant_code_batch(
                page,
                account_id,
                chunk_codes,
                chunk_groups,
                dry_run=dry_run,
                try_spec_code_search=bool(delist_spec_code_search_enabled),
            )
        )

    if not results:
        _log(account_id, "校验完成，无可下架商品，跳过上架前下架")

    warnings: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        if item.get("status") == "delisted":
            continue
        err = str(item.get("error") or "").strip()
        if not err or err in NON_BLOCKING_DELIST_ITEM_ERRORS:
            if err in NON_BLOCKING_DELIST_ITEM_ERRORS:
                label = str(
                    item.get("selector")
                    or item.get("merchant_code")
                    or item.get("target_product_id")
                    or ""
                ).strip()
                warnings.append(f"{label}: {err}" if label else err)
            continue
        label = str(
            item.get("selector")
            or item.get("merchant_code")
            or item.get("target_product_id")
            or ""
        ).strip()
        warnings.append(f"{label}: {err}" if label else err)

    return {
        "account_id": account_id,
        "mode": "pipeline_relist_prep",
        "results": results,
        "errors": [],
        "warnings": warnings,
        "hit": sum(1 for r in results if r.get("status") == "delisted"),
        "scanned": len(results),
    }
