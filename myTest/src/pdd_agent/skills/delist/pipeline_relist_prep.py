"""整合链路 — 批量精准下架（商品编码空格筛选 + 商品ID校验通过才下架）。"""

from __future__ import annotations

from typing import Any

from pdd_agent.browser.shop_display_name import verify_shop_for_account
from pdd_agent.skills.delist.automation import (
    _log,
    filter_goods_by_merchant_codes,
    filter_goods_by_product_ids,
    open_goods_list_on_sale,
    process_single_product_delist,
    scan_filtered_product_rows_all_pages,
)

SKIP_REASON_FILTER_UNVERIFIED = "filter_verification_failed"
SKIP_REASON_ID_MISMATCH = "product_id_verification_failed"
SKIP_REASON_SET_FILTER_FAILED = "set_merchant_code_filter_failed"


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
    """
    校验筛选是否生效：每一行都必须命中预期商品编码之一。
    若出现无法匹配编码的行，视为筛选失败（可能展示了全部商品）。
    """
    expected = {str(code or "").strip() for code in merchant_codes if str(code or "").strip()}
    if not expected:
        return [], "missing_merchant_codes"

    verified: list[dict[str, Any]] = []
    for row in scanned_rows:
        product_id = str(row.get("product_id") or "").strip()
        merchant_code = str(row.get("merchant_code") or "").strip()
        if not product_id:
            continue
        if merchant_code not in expected:
            return [], SKIP_REASON_FILTER_UNVERIFIED
        verified.append(row)
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


def _delist_verified_product_ids(
    page,
    account_config: dict,
    delist_plan: list[dict[str, Any]],
    *,
    dry_run: bool,
) -> list[dict[str, Any]]:
    """仅对校验通过的商品ID逐条精准下架（不用全选批量下架）。"""
    account_id = str(account_config.get("account_id") or "")
    results: list[dict[str, Any]] = []
    ordered_ids = list(
        dict.fromkeys(
            str(item.get("target_product_id") or "").strip()
            for item in delist_plan
            if str(item.get("target_product_id") or "").strip()
        )
    )
    for idx, product_id in enumerate(ordered_ids, start=1):
        meta = next((item for item in delist_plan if item.get("target_product_id") == product_id), {})
        _log(account_id, f"精准下架 [{idx}/{len(ordered_ids)}] 商品ID={product_id}")
        stats = process_single_product_delist(
            page,
            account_config,
            product_id=product_id,
            mapping_id=str(meta.get("mapping_id") or ""),
            dry_run=dry_run,
            list_already_open=True,
        )
        stats["selector"] = meta.get("selector", "")
        stats["merchant_code"] = meta.get("merchant_code", "")
        results.append(stats)
    return results


def process_pipeline_relist_prep_delist(
    page,
    account_config: dict,
    targets: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    按商品编码批量筛选，校验每一行商品编码/商品ID 通过后才精准下架。

    校验失败时不执行任何下架，返回 delist_skipped=True，整合链路继续上架。
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
            product_id = str(raw.get("target_product_id") or raw.get("pdd_product_id") or "").strip()
            if not product_id:
                continue
            merchant_code = f"__id__:{product_id}"
        if merchant_code not in groups:
            groups[merchant_code] = {
                "merchant_code": merchant_code,
                "mapping_id": str(raw.get("mapping_id") or "").strip(),
                "selector": str(raw.get("selector") or "").strip(),
                "known_ids": [],
            }
        group = groups[merchant_code]
        if not group.get("mapping_id"):
            group["mapping_id"] = str(raw.get("mapping_id") or "").strip()
        if not group.get("selector"):
            group["selector"] = str(raw.get("selector") or "").strip()
        known_id = str(raw.get("target_product_id") or raw.get("pdd_product_id") or "").strip()
        if known_id and known_id not in group["known_ids"]:
            group["known_ids"].append(known_id)

    if not groups:
        return {
            "account_id": account_id,
            "mode": "pipeline_relist_prep",
            "results": [],
            "errors": [],
            "hit": 0,
            "scanned": 0,
        }

    if not open_goods_list_on_sale(page, account_id):
        return {
            "account_id": account_id,
            "mode": "pipeline_relist_prep",
            "results": [],
            "errors": ["打开商品列表失败"],
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
            "errors": [err],
            "hit": 0,
            "scanned": 0,
        }

    merchant_groups = {
        key: group for key, group in groups.items() if not str(key).startswith("__id__:")
    }
    id_only_groups = {
        key: group for key, group in groups.items() if str(key).startswith("__id__:")
    }

    merchant_codes = list(
        dict.fromkeys(
            str(group.get("merchant_code") or "").strip()
            for group in merchant_groups.values()
            if str(group.get("merchant_code") or "").strip()
        )
    )

    delist_plan: list[dict[str, Any]] = []

    if merchant_codes:
        _log(
            account_id,
            f"整合链路下架预备：店铺「{shop_check.actual}」，"
            f"批量筛选 {len(merchant_codes)} 个商品编码并校验商品ID",
        )
        if not filter_goods_by_merchant_codes(page, account_id, merchant_codes):
            return _skip_delist_result(
                account_id=account_id,
                skip_reason=SKIP_REASON_SET_FILTER_FAILED,
            )

        scanned_rows = scan_filtered_product_rows_all_pages(
            page,
            account_id,
            merchant_codes=merchant_codes,
        )
        verified_rows, verify_err = _verify_scanned_rows_for_merchant_codes(scanned_rows, merchant_codes)
        if verify_err:
            return _skip_delist_result(account_id=account_id, skip_reason=verify_err)

        discovered_by_code: dict[str, list[str]] = {code: [] for code in merchant_codes}
        for row in verified_rows:
            product_id = str(row.get("product_id") or "").strip()
            merchant_code = str(row.get("merchant_code") or "").strip()
            if product_id and merchant_code in discovered_by_code:
                discovered_by_code[merchant_code].append(product_id)

        id_verify_err = _verify_known_product_ids(merchant_groups, discovered_by_code)
        if id_verify_err:
            return _skip_delist_result(account_id=account_id, skip_reason=id_verify_err)

        for code, group in merchant_groups.items():
            mapping_id = str(group.get("mapping_id") or "")
            selector = str(group.get("selector") or "")
            known_ids = list(dict.fromkeys(str(pid).strip() for pid in (group.get("known_ids") or []) if str(pid).strip()))
            scanned_ids = list(dict.fromkeys(discovered_by_code.get(code, [])))

            if known_ids:
                product_ids = [pid for pid in scanned_ids if pid in known_ids]
                extra_ids = [pid for pid in scanned_ids if pid not in known_ids]
                if extra_ids:
                    _log(
                        account_id,
                        f"商品编码 {code} 另扫到 {len(extra_ids)} 个重复链接，将一并精准下架",
                    )
                    product_ids = list(dict.fromkeys([*product_ids, *extra_ids]))
            else:
                product_ids = scanned_ids

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
                delist_plan.append(
                    {
                        "mapping_id": mapping_id,
                        "selector": selector,
                        "merchant_code": code,
                        "target_product_id": product_id,
                    }
                )

    if id_only_groups:
        id_targets = list(
            dict.fromkeys(
                key.split(":", 1)[1]
                for key in id_only_groups
                if str(key).startswith("__id__:") and ":" in key
            )
        )
        id_targets = [pid for pid in id_targets if pid]
        if id_targets:
            _log(account_id, f"补充按 {len(id_targets)} 个商品ID筛选并校验")
            if not filter_goods_by_product_ids(page, account_id, id_targets):
                return _skip_delist_result(
                    account_id=account_id,
                    skip_reason=SKIP_REASON_SET_FILTER_FAILED,
                    results=results,
                )
            id_rows = scan_filtered_product_rows_all_pages(page, account_id)
            verified_id_rows, id_verify_err = _verify_scanned_rows_for_product_ids(id_rows, id_targets)
            if id_verify_err:
                return _skip_delist_result(
                    account_id=account_id,
                    skip_reason=id_verify_err,
                    results=results,
                )
            verified_id_set = {
                str(row.get("product_id") or "").strip() for row in verified_id_rows if row.get("product_id")
            }
            for key, group in id_only_groups.items():
                product_id = key.split(":", 1)[1]
                mapping_id = str(group.get("mapping_id") or "")
                selector = str(group.get("selector") or "")
                if product_id not in verified_id_set:
                    results.append(
                        {
                            "mapping_id": mapping_id,
                            "selector": selector,
                            "merchant_code": key,
                            "target_product_id": product_id,
                            "error": "product_id_not_found_on_sale",
                        }
                    )
                    continue
                delist_plan.append(
                    {
                        "mapping_id": mapping_id,
                        "selector": selector,
                        "merchant_code": key,
                        "target_product_id": product_id,
                    }
                )

    if delist_plan:
        delist_results = _delist_verified_product_ids(
            page,
            account_config,
            delist_plan,
            dry_run=dry_run,
        )
        results.extend(delist_results)
    elif not results:
        _log(account_id, "校验完成，无可下架商品，跳过上架前下架")

    blocking: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        if item.get("status") == "delisted":
            continue
        err = str(item.get("error") or "").strip()
        if err in {"", "product_id_not_found_on_sale"}:
            continue
        label = str(
            item.get("selector")
            or item.get("merchant_code")
            or item.get("target_product_id")
            or ""
        ).strip()
        blocking.append(f"{label}: {err}" if label else err)

    return {
        "account_id": account_id,
        "mode": "pipeline_relist_prep",
        "results": results,
        "errors": blocking,
        "hit": sum(1 for r in results if r.get("status") == "delisted"),
        "scanned": len(results),
    }
