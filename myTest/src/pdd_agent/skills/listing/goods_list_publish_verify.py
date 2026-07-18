"""提交后商品列表核验：在售中 → 已驳回 → 全部 Tab 兜底。"""

from __future__ import annotations

from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.domain.models import ListingUnit
from pdd_agent.skills.listing.goods_list_tab_navigation import (
    open_goods_list_with_tab,
    refresh_goods_list_with_tab,
)
from pdd_agent.skills.listing.pdd_listing_quality_v2 import (
    PublishSearchStep,
    quality_v2_enabled,
    run_quality_v2_publish_search,
)


def _upload_module():
    from pdd_agent.skills.listing import upload as listing_upload

    return listing_upload


def _capture_result(**kwargs: Any) -> dict[str, Any]:
    return _upload_module()._capture_result(**kwargs)


def _search_goods_tab(
    page: DpPage,
    account_id: str,
    unit: ListingUnit,
    *,
    tab_text: str,
    tab_key: str,
    merchant_code: str,
    title: str,
    max_attempts: int = 1,
    refresh_on_not_found: bool = False,
    require_title_match: bool | None = None,
) -> dict[str, Any]:
    upload = _upload_module()
    if not open_goods_list_with_tab(page, account_id, tab_text):
        return _capture_result(status="open_goods_list_failed", tab=tab_key)

    label = unit.listing_label
    attempts = max(1, int(max_attempts or 1))
    if require_title_match is None:
        require_title_match = tab_key != "rejected"
    for attempt in range(1, attempts + 1):
        matches = upload._execute_goods_tab_query(
            page,
            merchant_code,
            title,
            require_title_match=require_title_match,
        )
        if matches:
            selected = matches[0]
            if attempt > 1:
                print(
                    f"[{account_id}] [{label}] {tab_text} 第{attempt}次查询匹配成功",
                    flush=True,
                )
            return _capture_result(
                status="captured",
                tab=tab_key,
                pdd_product_id=str(selected.get("pdd_product_id") or ""),
                matched_created_at=str(selected.get("matched_created_at") or ""),
                matched_row_text=str(selected.get("row_text") or ""),
                list_status=str(selected.get("list_status") or ""),
                rejection_reason=str(selected.get("rejection_reason") or ""),
            )

        if attempt >= attempts or not refresh_on_not_found:
            break

        print(
            f"[{account_id}] [{label}] {tab_text} 第{attempt}次未匹配到商品，刷新页面后重试",
            flush=True,
        )
        refresh_goods_list_with_tab(page, tab_text, account_id=account_id)

    return _capture_result(status="not_found", tab=tab_key)


def _search_goods_all_tab(
    page: DpPage,
    account_id: str,
    unit: ListingUnit,
    merchant_code: str,
) -> dict[str, Any]:
    upload = _upload_module()
    label = unit.listing_label
    if not open_goods_list_with_tab(page, account_id, "全部"):
        return _capture_result(status="open_goods_list_failed", tab="all")

    print(
        f"[{account_id}] [{label}] 在售中/已驳回未匹配，改在全部Tab按商品编码核验",
        flush=True,
    )
    matches = upload._execute_goods_all_tab_query(page, merchant_code)
    if not matches:
        return _capture_result(status="not_found", tab="all")
    if len(matches) > 1:
        print(
            f"[{account_id}] [{label}] 全部Tab按商品编码命中 {len(matches)} 条记录，按要求仅取第1条核验",
            flush=True,
        )

    selected = matches[0]
    result = upload._evaluate_all_tab_row(selected, merchant_code)
    status = str(result.get("status") or "")
    if status == "captured":
        print(
            f"[{account_id}] [{label}] 全部Tab核验通过："
            f"product_id={result.get('pdd_product_id')} "
            f"库存={selected.get('total_inventory')} 状态={result.get('list_status')}",
            flush=True,
        )
    elif status == "zero_inventory":
        print(
            f"[{account_id}] [{label}] 全部Tab找到商品但总库存为0",
            flush=True,
        )
    elif status == "invalid_list_status":
        print(
            f"[{account_id}] [{label}] 全部Tab找到商品但状态={result.get('list_status') or '未知'}",
            flush=True,
        )
    return result


def capture_publish_outcome(
    page: DpPage,
    account_id: str,
    unit: ListingUnit,
    merchant_code: str,
    title: str,
) -> dict[str, Any]:
    """
    提交成功后核验商品最终状态：
    1. 在售中（最多 2 次，查不到刷新重试）
    2. 已驳回
    3. 全部 Tab 兜底
    """
    upload = _upload_module()
    label = unit.listing_label
    try:
        if quality_v2_enabled():
            def _search_step(step: PublishSearchStep) -> dict[str, Any]:
                return _search_goods_tab(
                    page,
                    account_id,
                    unit,
                    tab_text=step.tab_text,
                    tab_key=step.tab_key,
                    merchant_code=merchant_code,
                    title=title,
                    max_attempts=step.attempts,
                    refresh_on_not_found=step.refresh_on_not_found,
                    require_title_match=False,
                )

            result = run_quality_v2_publish_search(
                search_tab=_search_step,
                search_all=lambda: _search_goods_all_tab(
                    page,
                    account_id,
                    unit,
                    merchant_code,
                ),
            )
            print(
                f"[{account_id}] [{label}] 拼多多上架修复流程核验："
                f"status={result.get('status')} tabs={'/'.join(result.get('searched_tabs') or [])}",
                flush=True,
            )
            return result

        on_sale = _search_goods_tab(
            page,
            account_id,
            unit,
            tab_text="在售中",
            tab_key="on_sale",
            merchant_code=merchant_code,
            title=title,
            max_attempts=2,
            refresh_on_not_found=True,
        )
        if on_sale["status"] == "captured" and on_sale.get("pdd_product_id"):
            print(
                f"[{account_id}] [{label}] 已在在售中抓取商品ID={on_sale['pdd_product_id']}",
                flush=True,
            )
            return on_sale

        rejected = _search_goods_tab(
            page,
            account_id,
            unit,
            tab_text="已驳回",
            tab_key="rejected",
            merchant_code=merchant_code,
            title=title,
        )
        if rejected["status"] == "captured":
            rejected["status"] = "rejected"
            reason = str(rejected.get("rejection_reason") or "").strip()
            print(
                f"[{account_id}] [{label}] 商品发布后进入已驳回，按失败处理"
                + (f"：{reason[:80]}" if reason else ""),
                flush=True,
            )
            return rejected

        status = "not_found"
        if on_sale["status"] == "open_goods_list_failed" or rejected["status"] == "open_goods_list_failed":
            status = "open_goods_list_failed"
        print(
            f"[{account_id}] [{label}] 提交后未在在售中/已驳回匹配到本次商品",
            flush=True,
        )
        all_tab = _search_goods_all_tab(page, account_id, unit, merchant_code)
        if all_tab.get("status") != "not_found":
            return all_tab
        return _capture_result(
            status=status,
            message="提交成功页已出现，但商品列表未匹配到本次发布记录",
        )
    except Exception as exc:
        err = upload._safe_exc(exc)
        print(f"[{account_id}] [{label}] 抓取商品ID异常：{err}", flush=True)
        return _capture_result(status="capture_error", message=err)
