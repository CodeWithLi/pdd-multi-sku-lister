"""负库存恢复上架 — 在拼多多「已下架」列表按商品编码搜索并点击「上架」。"""

from __future__ import annotations

import time
from typing import Any, Literal

from pdd_agent.browser.shop_display_name import verify_shop_for_account
from pdd_agent.skills.delist.automation import (
    _clear_goods_filters,
    _dismiss_pdd_blocking_modals,
    _get_table_rows,
    _goods_list_empty_state,
    _scan_filtered_rows_on_page,
    _wait_goods_list_search_settled,
    extract_merchant_code_from_row_text,
    extract_product_id_from_text,
    merchant_code_matches_expected,
)

RelistRowStrategy = Literal["first", "by_product_id"]

RELIST_ROW_STRATEGY: RelistRowStrategy = "by_product_id"
PRODUCT_ID_MISMATCH_MESSAGE = "当前商品重新上架失败，商品id匹配不上"


def _log(account_id: str, msg: str) -> None:
    prefix = f"[{account_id}] " if account_id else ""
    print(f"{prefix}{msg}", flush=True)


def _find_relist_modal_root(page):
    try:
        return page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none' && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            function matchesRelistModal(text) {
                const t = (text || '').replace(/\\s+/g, '');
                if (!t) return false;
                if (t.includes('确定上架商品') || t.includes('确认上架商品')) return true;
                return t.includes('上架') && (t.includes('确定') || t.includes('确认')) && t.includes('取消');
            }
            const roots = document.querySelectorAll(
                '[data-testid="beast-core-modal"], .ant-modal-wrap, .ant-modal, '
                + '[class*="MDL_modal"], [class*="MDL_outer"], [role="dialog"]'
            );
            for (const el of roots) {
                if (!isVisible(el)) continue;
                if (matchesRelistModal(el.innerText || el.textContent || '')) return el;
            }
            return null;
            """
        )
    except Exception:
        return None


def _click_confirm_in_relist_modal(page, account_id: str) -> bool:
    time.sleep(0.5)
    clicked = page.run_js(
        """
        function isVisible(el) {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 2 && r.height > 2
                && s.display !== 'none' && s.visibility !== 'hidden';
        }
        const okBtn = document.querySelector('[data-testid="beast-core-modal-ok-button"]');
        if (okBtn && isVisible(okBtn)) {
            okBtn.click();
            return 'testid_ok';
        }
        function findModalRoot() {
            const markers = ['确定上架商品', '确认上架商品'];
            const candidates = document.querySelectorAll(
                '[data-testid="beast-core-modal"], .ant-modal-wrap, .ant-modal, [role="dialog"]'
            );
            for (const el of candidates) {
                if (!isVisible(el)) continue;
                const t = el.innerText || '';
                if (markers.some((m) => t.includes(m))) return el;
                if (t.includes('上架') && t.includes('确定') && t.includes('取消')) return el;
            }
            return null;
        }
        function clickConfirm(root) {
            const prefer = root.querySelectorAll(
                'button[data-testid="beast-core-modal-ok-button"], button[class*="primary"]'
            );
            for (const btn of prefer) {
                const t = (btn.innerText || btn.textContent || '').trim();
                if ((t === '确定' || t === '确认') && isVisible(btn)) {
                    btn.click();
                    return 'primary';
                }
            }
            for (const btn of root.querySelectorAll('button, a, span')) {
                const t = (btn.innerText || btn.textContent || '').trim();
                if (t === '确定' && isVisible(btn)) {
                    btn.click();
                    return 'text';
                }
            }
            return null;
        }
        const root = findModalRoot();
        if (root) return clickConfirm(root);
        return null;
        """
    )
    if clicked:
        _log(account_id, f"已在弹窗内点击「确认」（{clicked}）")
        time.sleep(1.2)
        return True
    _log(account_id, "未能在弹窗内点击「确认」")
    return False


def _relist_row_via_action_link(page, row, account_id: str, product_id: str) -> bool:
    try:
        _dismiss_pdd_blocking_modals(page, account_id, "恢复上架-点击上架前")
        link = row.ele("text:上架", timeout=2)
        if link:
            link.click()
        else:
            clicked = page.run_js(
                """
                const tr = arguments[0];
                if (!tr) return false;
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 2 && r.height > 2;
                }
                const nodes = tr.querySelectorAll('a, button, span, div');
                for (const n of nodes) {
                    const t = (n.innerText || n.textContent || '').trim();
                    if (t !== '上架' || !isVisible(n)) continue;
                    try { n.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
                    n.click();
                    return true;
                }
                return false;
                """,
                row,
            )
            if not clicked:
                _log(account_id, f"  行内未找到「上架」链接 ID={product_id}")
                return False
        time.sleep(0.8)
        if _find_relist_modal_root(page) and _click_confirm_in_relist_modal(page, account_id):
            return True
        return False
    except Exception as exc:
        _log(account_id, f"  行内上架异常 ID={product_id}: {exc}")
        return False


def _extract_product_id_from_row(row) -> str:
    """优先从 span.goods-id 读取商品 ID，与拼多多已下架列表 DOM 结构一致。"""
    try:
        via_dom = row.run_js(
            """
            const tr = arguments[0];
            if (!tr) return '';
            const pick = tr.querySelector('span.goods-id span')
                || tr.querySelector('.goods-id span')
                || tr.querySelector('span.goods-id');
            if (!pick) return '';
            const text = (pick.innerText || pick.textContent || '').trim();
            return /^\\d{10,}$/.test(text) ? text : '';
            """
        )
        if via_dom:
            return str(via_dom).strip()
    except Exception:
        pass
    try:
        text = row.text or ""
    except Exception:
        text = ""
    return str(extract_product_id_from_text(text) or "").strip()


def _enrich_rows_product_ids(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in rows:
        row = item.get("row")
        product_id = str(item.get("product_id") or "").strip()
        if row:
            product_id = _extract_product_id_from_row(row) or product_id
        enriched.append({**item, "product_id": product_id})
    return enriched


def _pick_row_by_product_id(
    rows: list[dict[str, Any]],
    target_product_id: str,
) -> tuple[dict[str, Any] | None, int]:
    target = str(target_product_id or "").strip()
    if not target:
        return None, 0
    for index, item in enumerate(rows, start=1):
        product_id = str(item.get("product_id") or "").strip()
        if product_id == target:
            return item, index
    return None, 0


def _pick_row_by_strategy(
    rows: list[dict[str, Any]],
    product_code: str,
    *,
    strategy: RelistRowStrategy = "first",
    target_product_id: str = "",
) -> tuple[dict[str, Any] | None, int]:
    if not rows:
        return None, 0
    enriched = _enrich_rows_product_ids(rows)
    target_id = str(target_product_id or "").strip()
    if strategy == "by_product_id" and target_id:
        picked, index = _pick_row_by_product_id(enriched, target_id)
        if picked:
            return picked, index
        return None, 0

    expected = {str(product_code or "").strip()}
    matched = [
        item
        for item in enriched
        if merchant_code_matches_expected(str(item.get("merchant_code") or ""), expected)
        or merchant_code_matches_expected(
            extract_merchant_code_from_row_text(str(item.get("row_text") or "")),
            expected,
        )
    ]
    pool = matched or enriched
    if strategy == "first" or not target_id:
        return pool[0], 1
    return None, 0


def _search_delisted_by_merchant_code(page, account_id: str, merchant_code: str) -> str:
    """在已下架 Tab 搜索单个商品编码。返回 ready / empty / timeout。"""
    from pdd_agent.skills.listing.upload import (
        _click_goods_search as click_search,
        _fill_goods_merchant_code_filter,
    )

    code = str(merchant_code or "").strip()
    if not code:
        return "empty"
    _clear_goods_filters(page)
    fill_result = _fill_goods_merchant_code_filter(page, code)
    if not fill_result.get("filled"):
        _log(account_id, f"商品编码筛选框写入失败：{code}")
        return "empty"
    search_result = click_search(page)
    if not search_result.get("clicked"):
        _log(account_id, "未点击到「查询」按钮")
        return "empty"
    state = _wait_goods_list_search_settled(page, account_id)
    _dismiss_pdd_blocking_modals(page, account_id, "恢复上架-搜索后")
    _log(
        account_id,
        f"已搜索商品编码 {code}，状态={state}，可见行={len(_get_table_rows(page))}",
    )
    return state


def relist_one_product_code(
    page,
    account_id: str,
    *,
    product_code: str,
    target_pdd_product_id: str = "",
    dry_run: bool = False,
    row_strategy: RelistRowStrategy = RELIST_ROW_STRATEGY,
) -> dict[str, Any]:
    """在已下架列表搜索单个编码，按商品 ID 精准匹配后上架对应行。"""
    code = str(product_code or "").strip()
    target_id = str(target_pdd_product_id or "").strip()
    result: dict[str, Any] = {
        "product_code": code,
        "status": "failed",
        "message": "",
        "pdd_product_id": target_id,
        "target_pdd_product_id": target_id,
        "merchant_code": code,
    }
    if not code:
        result["message"] = "缺少商品编码"
        result["status"] = "skipped"
        return result

    state = _search_delisted_by_merchant_code(page, account_id, code)
    if state == "empty" or _goods_list_empty_state(page):
        result["status"] = "not_found"
        result["message"] = "没有搜索到该商品"
        return result

    rows = _enrich_rows_product_ids(_scan_filtered_rows_on_page(page))
    if not rows:
        result["status"] = "not_found"
        result["message"] = "没有搜索到该商品"
        return result

    effective_strategy: RelistRowStrategy = "by_product_id" if target_id else row_strategy
    picked, row_index = _pick_row_by_strategy(
        rows,
        code,
        strategy=effective_strategy,
        target_product_id=target_id,
    )
    if not picked:
        if target_id:
            visible_ids = [str(item.get("product_id") or "").strip() for item in rows if item.get("product_id")]
            _log(
                account_id,
                f"商品编码 {code} 搜索到 {len(rows)} 行，未匹配目标商品ID={target_id}"
                + (f"（页面ID：{', '.join(visible_ids)}）" if visible_ids else ""),
            )
            result["status"] = "failed"
            result["message"] = PRODUCT_ID_MISMATCH_MESSAGE
            return result
        result["status"] = "not_found"
        result["message"] = "没有搜索到该商品"
        return result

    product_id = str(picked.get("product_id") or "").strip()
    row_merchant = str(picked.get("merchant_code") or "").strip() or code
    result["pdd_product_id"] = product_id
    result["merchant_code"] = row_merchant
    if row_index > 0:
        _log(account_id, f"商品编码 {code} 第 {row_index} 行匹配商品ID={product_id}")

    if dry_run:
        result["status"] = "dry_run"
        result["message"] = f"联调模拟上架（dry_run）商品ID={product_id}"
        return result

    row = picked.get("row")
    if not row:
        result["message"] = "无法定位表格行"
        return result

    if _relist_row_via_action_link(page, row, account_id, product_id):
        result["status"] = "relisted"
        result["message"] = f"已上架商品ID={product_id}"
    else:
        result["message"] = "点击上架或确认失败"
    return result


def process_inventory_relist(
    page,
    account_config: dict,
    targets: list[dict[str, Any]],
    *,
    dry_run: bool = False,
    row_strategy: RelistRowStrategy = RELIST_ROW_STRATEGY,
) -> dict[str, Any]:
    """
    负库存恢复上架主流程。

    targets 每项：{product_code, record_ids?, merchant_code?}
    """
    from pdd_agent.skills.listing.goods_list_tab_navigation import open_goods_list_with_tab

    account_id = str(account_config.get("account_id") or "")
    stats: dict[str, Any] = {
        "account_id": account_id,
        "mode": "inventory_relist",
        "dry_run": bool(dry_run),
        "row_strategy": row_strategy,
        "results": [],
        "warnings": [],
        "errors": [],
    }

    shop_check = verify_shop_for_account(
        account_id,
        page,
        login_username=str(account_config.get("username") or account_config.get("login_username") or ""),
    )
    if not shop_check.ok:
        err = (
            f"店铺校验失败：期望「{shop_check.expected or account_id}」，"
            f"当前页面「{shop_check.actual or '未知'}」({shop_check.error})"
        )
        stats["errors"].append(err)
        return stats

    if not open_goods_list_with_tab(page, account_id, "已下架"):
        stats["errors"].append("无法打开商品列表或切换到「已下架」")
        return stats

    _dismiss_pdd_blocking_modals(page, account_id, "恢复上架")

    normalized_targets = [
        {
            "product_code": str(item.get("product_code") or item.get("merchant_code") or "").strip(),
            "record_ids": list(item.get("record_ids") or []),
            "pdd_product_id": str(item.get("pdd_product_id") or "").strip(),
        }
        for item in (targets or [])
        if str(item.get("product_code") or item.get("merchant_code") or "").strip()
    ]
    if not normalized_targets:
        stats["warnings"].append("无待恢复上架商品编码")
        return stats

    for item in normalized_targets:
        code = item["product_code"]
        row_result = relist_one_product_code(
            page,
            account_id,
            product_code=code,
            target_pdd_product_id=str(item.get("pdd_product_id") or "").strip(),
            dry_run=dry_run,
            row_strategy=row_strategy,
        )
        row_result["record_ids"] = list(item.get("record_ids") or [])
        stats["results"].append(row_result)
        time.sleep(0.8)

    relisted = sum(1 for r in stats["results"] if r.get("status") == "relisted")
    not_found = sum(1 for r in stats["results"] if r.get("status") == "not_found")
    _log(
        account_id,
        f"恢复上架完成：共 {len(stats['results'])} 个编码，"
        f"成功 {relisted}，未找到 {not_found}",
    )
    return stats
