"""整合链路 — 批量精准下架（商品编码空格批量筛选 + 批量下架）。"""

from __future__ import annotations

from typing import Any

from pdd_agent.browser.shop_display_name import verify_shop_for_account
from pdd_agent.skills.delist.automation import (
    _log,
    batch_delist_filtered_goods,
    filter_goods_by_merchant_codes,
    filter_goods_by_product_ids,
    open_goods_list_on_sale,
    scan_filtered_product_rows_all_pages,
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


def process_pipeline_relist_prep_delist(
    page,
    account_config: dict,
    targets: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    按商品编码批量下架全部在售重复链接。

    流程：打开商品列表一次 → 商品编码空格批量筛选 → 翻页扫描 → 逐页全选批量下架。
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
        key: group
        for key, group in groups.items()
        if not str(key).startswith("__id__:")
    }
    id_only_groups = {
        key: group
        for key, group in groups.items()
        if str(key).startswith("__id__:")
    }

    merchant_codes = [str(group.get("merchant_code") or "").strip() for group in merchant_groups.values()]
    merchant_codes = list(dict.fromkeys(code for code in merchant_codes if code))

    discovered_by_code: dict[str, list[str]] = {code: [] for code in merchant_codes}
    delist_ids: set[str] = set()

    if merchant_codes:
        _log(
            account_id,
            f"整合链路下架预备：店铺「{shop_check.actual}」，"
            f"批量筛选 {len(merchant_codes)} 个商品编码",
        )
        if not filter_goods_by_merchant_codes(page, account_id, merchant_codes):
            for group in merchant_groups.values():
                results.append(
                    {
                        "mapping_id": group.get("mapping_id", ""),
                        "selector": group.get("selector", ""),
                        "merchant_code": group.get("merchant_code", ""),
                        "error": "set_merchant_code_filter_failed",
                    }
                )
        else:
            scanned_rows = scan_filtered_product_rows_all_pages(
                page,
                account_id,
                merchant_codes=merchant_codes,
            )
            for row in scanned_rows:
                product_id = str(row.get("product_id") or "").strip()
                matched_code = str(row.get("merchant_code") or "").strip()
                if not product_id:
                    continue
                delist_ids.add(product_id)
                if matched_code and matched_code in discovered_by_code:
                    discovered_by_code[matched_code].append(product_id)

            for code, group in merchant_groups.items():
                mapping_id = str(group.get("mapping_id") or "")
                selector = str(group.get("selector") or "")
                known_ids = list(dict.fromkeys(group.get("known_ids") or []))
                product_ids = list(dict.fromkeys([*discovered_by_code.get(code, []), *known_ids]))
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
                    delist_ids.add(product_id)
                    results.append(
                        {
                            "mapping_id": mapping_id,
                            "selector": selector,
                            "merchant_code": code,
                            "target_product_id": product_id,
                            "pending_delist": True,
                        }
                    )

            if delist_ids and filter_goods_by_merchant_codes(page, account_id, merchant_codes):
                hit, batch_errors = batch_delist_filtered_goods(page, account_id, dry_run=dry_run)
                _apply_batch_delist_outcome(results, hit=hit, errors=batch_errors, dry_run=dry_run)
            elif merchant_codes and not delist_ids:
                _log(account_id, "批量筛选后未找到可下架商品")

    if id_only_groups:
        id_targets = [key.split(":", 1)[1] for key in id_only_groups if ":" in key]
        id_targets = list(dict.fromkeys(pid for pid in id_targets if pid))
        if id_targets:
            _log(account_id, f"补充按 {len(id_targets)} 个商品ID批量下架")
            if filter_goods_by_product_ids(page, account_id, id_targets):
                id_rows = scan_filtered_product_rows_all_pages(page, account_id)
                id_found = {
                    str(row.get("product_id") or "").strip()
                    for row in id_rows
                    if str(row.get("product_id") or "").strip()
                }
                id_results: list[dict[str, Any]] = []
                for key, group in id_only_groups.items():
                    product_id = key.split(":", 1)[1]
                    mapping_id = str(group.get("mapping_id") or "")
                    selector = str(group.get("selector") or "")
                    if product_id not in id_found:
                        id_results.append(
                            {
                                "mapping_id": mapping_id,
                                "selector": selector,
                                "merchant_code": key,
                                "target_product_id": product_id,
                                "error": "product_id_not_found_on_sale",
                            }
                        )
                        continue
                    id_results.append(
                        {
                            "mapping_id": mapping_id,
                            "selector": selector,
                            "merchant_code": key,
                            "target_product_id": product_id,
                            "pending_delist": True,
                        }
                    )
                if any(item.get("pending_delist") for item in id_results):
                    hit, batch_errors = batch_delist_filtered_goods(page, account_id, dry_run=dry_run)
                    _apply_batch_delist_outcome(id_results, hit=hit, errors=batch_errors, dry_run=dry_run)
                results.extend(id_results)

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


def _apply_batch_delist_outcome(
    results: list[dict[str, Any]],
    *,
    hit: int,
    errors: list[str],
    dry_run: bool,
) -> None:
    pending = [item for item in results if item.get("pending_delist")]
    if errors:
        err_text = errors[0]
        for item in pending:
            item.pop("pending_delist", None)
            item["error"] = err_text
        return

    if dry_run:
        for item in pending:
            item.pop("pending_delist", None)
            item["status"] = "dry_run"
            item["hit"] = 1
        return

    if hit <= 0:
        for item in pending:
            item.pop("pending_delist", None)
            item["error"] = "batch_delist_no_hits"
        return

    for item in pending:
        item.pop("pending_delist", None)
        item["status"] = "delisted"
        item["hit"] = 1
