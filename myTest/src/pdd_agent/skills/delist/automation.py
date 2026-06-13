"""
拼多多商品列表自动下架（严格按创建时间门槛）

安全策略：
1. 仅处理「在售中」列表
2. 创建时间必须严格大于用户配置的门槛（相等也不下架）
3. 点击前对同一行二次读取并校验时间
4. 无法解析创建时间 → 跳过
5. 可选商家编码包含过滤
6. 支持 dry_run（只扫描不点击）
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass

from pdd_agent.paths import PROJECT_ROOT
from pdd_agent.skills.delist.time_utils import (
    extract_created_at_from_text,
    extract_product_id_from_text,
    format_datetime,
    is_eligible_for_delist,
    parse_threshold,
)

GOODS_LIST_URLS = (
    "https://mms.pinduoduo.com/goods/goods_list",
    "https://mms.pinduoduo.com/goods/goods-list",
    "https://mms.pinduoduo.com/goods/list",
)

MAX_PAGES = 50


@dataclass
class DelistSettings:
    min_created_after: str
    dry_run: bool = True
    merchant_code_contains: str = ""
    max_delist_per_run: int = 50
    account_ids: list[str] | None = None


def _log(account_id: str, msg: str):
    prefix = f"[{account_id}] " if account_id else ""
    print(f"{prefix}{msg}")


def _error_screenshot_path(filename: str) -> str:
    d = PROJECT_ROOT / "data" / "runs" / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / filename)


def load_delist_settings(config: dict) -> DelistSettings:
    raw = config.get("delist_settings") or {}
    return DelistSettings(
        min_created_after=raw.get("min_created_after", ""),
        dry_run=bool(raw.get("dry_run", True)),
        merchant_code_contains=(raw.get("merchant_code_contains") or "").strip(),
        max_delist_per_run=int(raw.get("max_delist_per_run", 50) or 50),
        account_ids=raw.get("account_ids"),
    )


def resolve_target_accounts(config: dict, settings: DelistSettings) -> list[dict]:
    accounts = config.get("accounts") or []
    if settings.account_ids:
        allowed = set(settings.account_ids)
        return [a for a in accounts if a.get("account_id") in allowed]
    return [a for a in accounts if a.get("enabled")]


def open_goods_list_on_sale(page, account_id: str) -> bool:
    """进入商品列表并切换到「在售中」。"""
    opened = False
    for url in GOODS_LIST_URLS:
        _log(account_id, f"尝试打开商品列表：{url}")
        page.get(url)
        time.sleep(3)
        if "login" in page.url:
            return False
        if page.ele("text:商品列表", timeout=2) or page.ele("text:创建时间", timeout=2):
            opened = True
            break

    if not opened:
        _log(account_id, "未能确认进入商品列表页，仍将尝试查找表格")
        page.get(GOODS_LIST_URLS[0])
        time.sleep(3)

    tab = page.ele("text:在售中", timeout=10)
    if tab:
        tab.click()
        time.sleep(2)
        _log(account_id, "已切换到「在售中」")
        return True

    _log(account_id, "未找到「在售中」标签，中止（避免误操作其他状态商品）")
    return False


def _get_table_rows(page):
    rows = page.eles("css:tbody tr")
    if rows:
        return [r for r in rows if (r.text or "").strip()]
    rows = page.eles("tag:tr")
    return [r for r in rows if (r.text or "").strip() and "创建时间" not in (r.text or "")]


def _row_passes_merchant_filter(row_text: str, code_filter: str) -> bool:
    if not code_filter:
        return True
    return code_filter in row_text


def _modal_is_open(page) -> bool:
    return bool(
        page.ele("text:确定下架商品", timeout=0.3)
        or page.ele("text:确定下架商品?", timeout=0.3)
    )


def _wait_delist_confirm_modal(page, account_id: str, timeout: int = 10) -> bool:
    """等待「确定下架商品?」弹窗出现。"""
    for _ in range(timeout):
        if _modal_is_open(page):
            return True
        time.sleep(0.5)
    _log(account_id, "未出现「确定下架商品」确认弹窗")
    return False


def _dismiss_delist_modal(page, account_id: str):
    """关闭未完成的下架弹窗，避免挡住下一行操作。"""
    if not _modal_is_open(page):
        return
    page.run_js(
        """
        function clickCancelInModal() {
            const walk = (root) => {
                if (!root || !root.innerText) return null;
                if (!root.innerText.includes('确定下架商品')) return null;
                const nodes = root.querySelectorAll('button, a, span, div');
                for (const n of nodes) {
                    const t = (n.innerText || n.textContent || '').trim();
                    if (t === '取消') return n;
                }
                return null;
            };
            for (const sel of ['.ant-modal-wrap', '[class*="modal"]', '[class*="Modal"]', '[role="dialog"]']) {
                for (const w of document.querySelectorAll(sel)) {
                    const btn = walk(w);
                    if (btn) { btn.click(); return true; }
                }
            }
            return false;
        }
        clickCancelInModal();
        """
    )
    time.sleep(0.5)
    _log(account_id, "已尝试关闭下架确认弹窗")


def _click_confirm_in_delist_modal(page, account_id: str) -> bool:
    """
    在「确定下架商品?」弹窗内点击「确定」主按钮。
    拼多多弹窗可能不是 ant-modal，需多策略匹配。
    """
    time.sleep(0.5)

    # 策略 1：JS 在含「确定下架商品」的弹层内找「确定」按钮
    clicked = page.run_js(
        """
        function isVisible(el) {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 2 && r.height > 2
                && s.display !== 'none' && s.visibility !== 'hidden' && parseFloat(s.opacity) > 0.1;
        }
        function findModalRoot() {
            const candidates = document.querySelectorAll(
                '.ant-modal-wrap, .ant-modal, [class*="modal"], [class*="Modal"], [class*="dialog"], [class*="Dialog"], [role="dialog"]'
            );
            for (const el of candidates) {
                if (!isVisible(el)) continue;
                const t = el.innerText || '';
                if (t.includes('确定下架商品') || (t.includes('下架') && t.includes('取消') && t.includes('确定'))) {
                    return el;
                }
            }
            const all = document.querySelectorAll('div, section');
            for (const el of all) {
                if (!isVisible(el)) continue;
                const t = (el.innerText || '').trim();
                if (t.length > 200) continue;
                if (t.includes('确定下架商品') && t.includes('取消') && t.includes('确定')) {
                    return el;
                }
            }
            return null;
        }
        function clickConfirm(root) {
            const prefer = root.querySelectorAll(
                'button.ant-btn-primary, button[class*="primary"], button[class*="confirm"], .ant-btn-primary'
            );
            for (const btn of prefer) {
                const t = (btn.innerText || btn.textContent || '').trim();
                if (t === '确定' && isVisible(btn)) {
                    btn.click();
                    return 'primary';
                }
            }
            const nodes = root.querySelectorAll('button, a, div, span');
            for (const btn of nodes) {
                const t = (btn.innerText || btn.textContent || '').trim();
                if (t !== '确定' || !isVisible(btn)) continue;
                const cls = (btn.className || '') + '';
                if (cls.includes('cancel') || cls.includes('Cancel')) continue;
                btn.click();
                return 'text';
            }
            return null;
        }
        const root = findModalRoot();
        if (root) return clickConfirm(root);
        if ((document.body.innerText || '').includes('确定下架商品')) {
            for (const btn of document.querySelectorAll('button')) {
                const t = (btn.innerText || btn.textContent || '').trim();
                if (t === '确定' && isVisible(btn)) {
                    btn.click();
                    return 'global';
                }
            }
        }
        return null;
        """
    )
    if clicked:
        _log(account_id, f"已通过 JS 点击弹窗「确定」（{clicked}）")
        return True

    # 策略 2：XPath 在弹窗祖先内找 button
    xpaths = (
        'xpath://*[contains(text(),"确定下架商品")]/ancestor::*[contains(@class,"modal") or contains(@class,"Modal") or @role="dialog"][1]//button[normalize-space()="确定"]',
        'xpath://button[normalize-space()="确定" and ancestor::*[contains(., "确定下架商品")]]',
        'xpath://*[contains(text(),"确定下架商品")]/following::button[normalize-space()="确定"][1]',
    )
    for xp in xpaths:
        btn = page.ele(xp, timeout=1)
        if btn:
            try:
                page.run_js('arguments[0].scrollIntoView({block:"center"});', btn)
                btn.click()
                _log(account_id, "已通过 XPath 点击弹窗「确定」")
                return True
            except Exception:
                pass

    # 策略 3：DrissionPage 取可见「确定」按钮（弹窗打开时通常有 1 个主按钮）
    if _modal_is_open(page):
        for btn in page.eles('xpath://button[normalize-space()="确定"]', timeout=1) or []:
            try:
                if btn.states.is_displayed:
                    btn.click()
                    _log(account_id, "已通过可见按钮列表点击「确定」")
                    return True
            except Exception:
                continue

    return False


def _verify_delist_success(page, account_id: str, product_id: str) -> bool:
    """弹窗关闭后，确认该商品不再显示「下架」操作（说明已不在售中）。"""
    for _ in range(12):
        time.sleep(1)
        if not page.ele("text:确定下架商品", timeout=0.3) and not page.ele(
            "text:确定下架商品?", timeout=0.3
        ):
            break

    if not product_id or product_id == "未知ID":
        return True

    still = page.ele(
        f'xpath://tr[contains(.,"{product_id}")]//*[normalize-space(text())="下架"]',
        timeout=2,
    )
    if still:
        _log(account_id, f"下架未生效：商品 {product_id} 仍在「在售中」列表（仍有「下架」按钮）")
        return False
    return True


def _confirm_delist_dialog(page, account_id: str, product_id: str) -> bool:
    """处理「确定下架商品?」弹窗并校验是否真正下架成功。"""
    time.sleep(0.5)
    if not _wait_delist_confirm_modal(page, account_id):
        return False

    if not _click_confirm_in_delist_modal(page, account_id):
        _log(account_id, "未能在弹窗内点击「确定」主按钮")
        return False

    _log(account_id, "已在弹窗内点击「确定」")
    time.sleep(1)

    if _verify_delist_success(page, account_id, product_id):
        _log(account_id, "下架成功：商品已从在售列表移除或不可再下架")
        return True

    return False


def _verify_row_before_delist(row, threshold, code_filter: str) -> tuple[bool, str, dict]:
    """
    点击前二次校验。返回 (允许下架, 原因, 行信息)。
    """
    text = row.text or ""
    created = extract_created_at_from_text(text)
    if not created:
        return False, "无法解析创建时间", {}

    if not is_eligible_for_delist(created, threshold):
        return False, f"创建时间 {format_datetime(created)} 不晚于门槛", {}

    if not _row_passes_merchant_filter(text, code_filter):
        return False, "商家编码不匹配过滤条件", {}

    product_id = extract_product_id_from_text(text) or "未知ID"
    info = {
        "product_id": product_id,
        "created_at": created,
        "created_raw": format_datetime(created),
    }
    return True, "通过校验", info


def _try_delist_row(page, row, account_id: str, threshold, settings: DelistSettings) -> str:
    """对单行执行下架或 dry_run。返回结果标签。"""
    ok, reason, info = _verify_row_before_delist(
        row, threshold, settings.merchant_code_contains
    )
    if not ok:
        return f"skip:{reason}"

    # 二次读取同一行，防止 DOM 变化或看错行
    ok2, reason2, info2 = _verify_row_before_delist(
        row, threshold, settings.merchant_code_contains
    )
    if not ok2:
        return f"abort:{reason2}"
    if info2.get("created_raw") != info.get("created_raw"):
        return "abort:二次校验创建时间不一致"

    pid = info2["product_id"]
    created_str = info2["created_raw"]
    _log(
        account_id,
        f"{'[试运行] 将下架' if settings.dry_run else '准备下架'} "
        f"商品ID={pid} 创建时间={created_str}",
    )

    if settings.dry_run:
        return "dry_run"

    link = row.ele("text:下架", timeout=2)
    if not link:
        return "skip:未找到下架链接"

    link.click()
    time.sleep(0.8)
    if not _confirm_delist_dialog(page, account_id, pid):
        _dismiss_delist_modal(page, account_id)
        return "abort:确认下架未成功"

    _log(account_id, f"已下架 商品ID={pid} 创建时间={created_str}")
    return "delisted"


MAX_PAGES = 200


def _first_row_signature(page) -> str:
    """用首行商品 ID 判断翻页后列表是否刷新。"""
    rows = _get_table_rows(page)
    if not rows:
        return ""
    text = rows[0].text or ""
    return extract_product_id_from_text(text) or text[:80]


def _wait_table_refresh(page, prev_sig: str, timeout: int = 12) -> bool:
    if not prev_sig:
        time.sleep(2)
        return True
    for _ in range(timeout):
        time.sleep(1)
        sig = _first_row_signature(page)
        if sig and sig != prev_sig:
            return True
    return False


def _click_next_page_number(page):
    """点击页码：当前激活页 + 1。"""
    active = page.ele("css:.ant-pagination-item-active", timeout=1)
    if not active:
        active = page.ele('css:[class*="pagination"][class*="active"]', timeout=1)
    if not active or not (active.text or "").strip().isdigit():
        return None

    nxt = int(active.text.strip()) + 1
    candidates = [
        page.ele(f'css:li.ant-pagination-item[title="{nxt}"]', timeout=1),
        page.ele(f'xpath://li[contains(@class,"pagination-item") and normalize-space(text())="{nxt}"]', timeout=1),
        page.ele(f'xpath://*[contains(@class,"pagination")]//*[normalize-space(text())="{nxt}"]', timeout=1),
    ]
    for c in candidates:
        if c:
            return c
    return None


def _find_next_page_button(page):
    """多种选择器查找「下一页」可点击元素。"""
    selectors = (
        'css:li.ant-pagination-next:not(.ant-pagination-disabled)',
        'css:.ant-pagination-next:not(.ant-pagination-disabled)',
        'css:[aria-label="下一页"]:not([disabled])',
        'css:.pagination-next:not(.disabled)',
        'xpath://li[contains(@class,"next") and not(contains(@class,"disabled"))]',
        'xpath://button[contains(normalize-space(.),"下一页") and not(@disabled)]',
        'xpath://a[contains(normalize-space(.),"下一页")]',
        'xpath://span[contains(normalize-space(.),"下一页")]/ancestor::li[1]',
        'xpath://*[contains(@class,"pagination")]//*[normalize-space(text())="›"]',
        'xpath://*[contains(@class,"pagination")]//*[normalize-space(text())=">"]',
    )
    for sel in selectors:
        btn = page.ele(sel, timeout=1)
        if not btn:
            continue
        cls = (btn.attr("class") or "") + (btn.attr("disabled") or "")
        if "disabled" in cls.lower():
            continue
        return btn
    return _click_next_page_number(page)


def _go_next_page_js(page) -> bool:
    """JS 兜底查找并点击下一页。"""
    clicked = page.run_js(
        """
        function isDisabled(el) {
            if (!el) return true;
            const cls = (el.className || '') + '';
            return el.disabled || cls.includes('disabled');
        }
        const byClass = document.querySelector(
            'li.ant-pagination-next:not(.ant-pagination-disabled), .ant-pagination-next:not(.ant-pagination-disabled)'
        );
        if (byClass && !isDisabled(byClass)) {
            byClass.click();
            return true;
        }
        const active = document.querySelector('.ant-pagination-item-active');
        if (active) {
            const cur = parseInt((active.textContent || '').trim(), 10);
            if (!isNaN(cur)) {
                const items = document.querySelectorAll('li.ant-pagination-item, [class*="pagination-item"]');
                for (const item of items) {
                    if (parseInt((item.textContent || '').trim(), 10) === cur + 1) {
                        item.click();
                        return true;
                    }
                }
            }
        }
        const nodes = document.querySelectorAll('a, button, span, li, div');
        for (const el of nodes) {
            const t = (el.textContent || '').trim();
            if (t === '下一页' && !isDisabled(el)) {
                el.click();
                return true;
            }
        }
        return false;
        """
    )
    return bool(clicked)


def _read_pagination_summary(page) -> str:
    """读取分页摘要（共 X 条 / 第 Y 页）。"""
    parts = []
    for sel in (
        "css:.ant-pagination-total-text",
        'xpath://*[contains(text(),"共") and contains(text(),"条")]',
        'xpath://*[contains(@class,"pagination") and contains(text(),"共")]',
    ):
        ele = page.ele(sel, timeout=1)
        if ele and (ele.text or "").strip():
            parts.append(ele.text.strip())
            break

    active = page.ele("css:.ant-pagination-item-active", timeout=1)
    if active and (active.text or "").strip():
        parts.append(f"当前页码 {active.text.strip()}")
    return "，".join(parts) if parts else ""


def _go_next_page(page, account_id: str) -> bool:
    prev_sig = _first_row_signature(page)
    summary = _read_pagination_summary(page)
    if summary:
        _log(account_id, f"分页信息：{summary}")

    btn = _find_next_page_button(page)
    if btn:
        try:
            page.run_js('arguments[0].scrollIntoView({block:"center"});', btn)
            time.sleep(0.3)
            btn.click()
            if _wait_table_refresh(page, prev_sig):
                _log(account_id, "已翻到下一页")
                return True
            _log(account_id, "点击下一页后列表未刷新，尝试 JS 兜底")
        except Exception as e:
            _log(account_id, f"点击下一页失败：{e}")

    if _go_next_page_js(page):
        time.sleep(1.5)
        if _wait_table_refresh(page, prev_sig):
            _log(account_id, "已通过 JS 翻到下一页")
            return True
        _log(account_id, "JS 翻页后列表未刷新")

    _log(account_id, "没有更多页，分页扫描结束")
    return False


def _clear_goods_filters(page) -> None:
    try:
        reset_btn = page.ele("text:重置", timeout=1.5)
        if reset_btn:
            reset_btn.click()
            time.sleep(1)
    except Exception:
        pass


def _set_goods_filter(page, label: str, value: str) -> bool:
    if not value:
        return False
    try:
        ok = page.run_js(
            """
            const [labelText, value] = arguments;
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            const nodes = Array.from(document.querySelectorAll('label, span, div'));
            for (const node of nodes) {
                const text = (node.innerText || node.textContent || '').trim();
                if (text !== labelText || !isVisible(node)) continue;
                let cur = node;
                for (let depth = 0; depth < 7 && cur; depth++, cur = cur.parentElement) {
                    const inputs = Array.from(cur.querySelectorAll?.('input') || []).filter(isVisible);
                    if (!inputs.length) continue;
                    const labelRect = node.getBoundingClientRect();
                    const input = inputs
                        .map((i) => ({ input: i, rect: i.getBoundingClientRect() }))
                        .filter((x) => x.rect.left > labelRect.left)
                        .sort((a, b) => Math.abs(a.rect.top - labelRect.top) - Math.abs(b.rect.top - labelRect.top))[0]?.input
                        || inputs[0];
                    input.focus();
                    input.value = '';
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.value = value;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
            }
            return false;
            """,
            label,
            value,
        )
        return bool(ok)
    except Exception:
        return False


def _click_goods_search(page) -> bool:
    from pdd_agent.skills.listing.upload import _click_goods_search as _click

    result = _click(page)
    return bool(result.get("clicked")) if isinstance(result, dict) else bool(result)


def _find_exact_product_row(page, product_id: str):
    rows = _get_table_rows(page)
    for row in rows:
        text = row.text or ""
        pid = extract_product_id_from_text(text) or ""
        if pid == product_id:
            return row
    return None


def process_single_product_delist(
    page,
    account_config: dict,
    *,
    product_id: str,
    mapping_id: str = "",
    dry_run: bool = False,
) -> dict:
    """精准下架单个已发布商品：只按拼多多商品ID匹配，ID不一致绝不下架。"""
    account_id = account_config.get("account_id", "")
    product_id = (product_id or "").strip()
    stats = {
        "account_id": account_id,
        "mapping_id": mapping_id,
        "target_product_id": product_id,
        "scanned": 0,
        "hit": 0,
        "dry_run": dry_run,
    }
    if not product_id:
        stats["error"] = "missing_product_id"
        return stats

    try:
        _log(account_id, f"开始精准下架商品ID={product_id}")
        if not open_goods_list_on_sale(page, account_id):
            stats["error"] = "open_list_failed"
            return stats

        _clear_goods_filters(page)
        if not _set_goods_filter(page, "商品ID", product_id):
            stats["error"] = "set_product_id_filter_failed"
            return stats
        _click_goods_search(page)

        rows = _get_table_rows(page)
        stats["scanned"] = len(rows)
        row = _find_exact_product_row(page, product_id)
        if not row:
            stats["error"] = "product_id_not_found_on_sale"
            _log(account_id, f"在售中未找到商品ID={product_id}")
            return stats

        text = row.text or ""
        matched_id = extract_product_id_from_text(text) or ""
        if matched_id != product_id:
            stats["error"] = f"product_id_mismatch:{matched_id}"
            return stats

        if dry_run:
            stats["hit"] = 1
            stats["status"] = "dry_run"
            _log(account_id, f"[试运行] 精准命中商品ID={product_id}，不会下架")
            return stats

        link = row.ele("text:下架", timeout=2)
        if not link:
            stats["error"] = "delist_link_not_found"
            return stats
        link.click()
        time.sleep(0.8)
        if not _confirm_delist_dialog(page, account_id, product_id):
            _dismiss_delist_modal(page, account_id)
            stats["error"] = "confirm_delist_failed"
            return stats

        stats["hit"] = 1
        stats["status"] = "delisted"
        _log(account_id, f"精准下架成功 商品ID={product_id}")
        return stats
    except Exception as e:
        stats["error"] = str(e)
        _log(account_id, f"精准下架异常: {e}")
        try:
            shot_path = _error_screenshot_path(f"error_delist_single_{account_id}_{product_id}.png")
            page.get_screenshot(path=shot_path)
            stats["screenshot"] = shot_path
        except Exception:
            pass
        return stats


def process_account_delist(page, account_config: dict, settings: DelistSettings) -> dict:
    """对已登录的 DpPage 执行下架扫描（调用方负责浏览器生命周期）。"""
    account_id = account_config.get("account_id", "")
    threshold = parse_threshold(settings.min_created_after)
    _log(
        account_id,
        f"下架门槛：仅创建时间严格晚于 {format_datetime(threshold)} 的商品可下架",
    )
    _log(account_id, f"单店目标：最多处理 {settings.max_delist_per_run} 条（跨页累计）")
    if settings.dry_run:
        _log(account_id, "当前为试运行模式：只扫描记录，不会点击下架")

    stats = {
        "account_id": account_id,
        "scanned": 0,
        "skipped_old": 0,
        "skipped_other": 0,
        "hit": 0,
        "pages": 0,
    }

    try:
        _log(account_id, "开始执行商品下架任务")
        if not open_goods_list_on_sale(page, account_id):
            stats["error"] = "open_list_failed"
            return stats

        for page_num in range(1, MAX_PAGES + 1):
            rows = _get_table_rows(page)
            stats["pages"] = page_num
            _log(account_id, f"第 {page_num} 页，扫描 {len(rows)} 行")
            if not rows:
                _log(account_id, "当前页无数据，结束分页")
                break

            page_hit = 0
            page_skipped_old = 0
            page_failed = 0
            for row in rows:
                stats["scanned"] += 1
                text = row.text or ""
                created = extract_created_at_from_text(text)
                if not created:
                    stats["skipped_other"] += 1
                    continue
                if not is_eligible_for_delist(created, threshold):
                    stats["skipped_old"] += 1
                    page_skipped_old += 1
                    continue

                if stats["hit"] >= settings.max_delist_per_run:
                    _log(account_id, f"已达单店上限 {settings.max_delist_per_run} 条，停止")
                    return stats

                result = _try_delist_row(page, row, account_id, threshold, settings)
                if result in ("delisted", "dry_run"):
                    stats["hit"] += 1
                    page_hit += 1
                    if result == "delisted":
                        time.sleep(random_delay())
                    if stats["hit"] >= settings.max_delist_per_run:
                        _log(account_id, f"已达单店上限 {settings.max_delist_per_run} 条，停止")
                        return stats
                elif result.startswith("abort:"):
                    page_failed += 1

            _log(
                account_id,
                f"第 {page_num} 页完成：命中 {page_hit} 条，"
                f"下架失败 {page_failed} 条，早于门槛跳过 {page_skipped_old} 条",
            )

            if stats["hit"] >= settings.max_delist_per_run:
                _log(account_id, f"已达单店上限 {settings.max_delist_per_run} 条，停止")
                break

            if page_failed > 0:
                _log(
                    account_id,
                    "本页有符合时间门槛的商品，但确认下架未成功，任务停止（请检查弹窗或重试）",
                )
                break

            # 时间早停：本页已无符合门槛的商品（列表按时间往下扫到门槛以下）
            if page_hit == 0:
                if page_skipped_old > 0:
                    _log(
                        account_id,
                        "本页剩余商品创建时间均已不晚于门槛，停止翻页"
                        f"（已命中 {stats['hit']} 条，未达上限 {settings.max_delist_per_run} 也会停止）",
                    )
                else:
                    _log(account_id, "本页无符合门槛的商品，停止翻页")
                break

            if not _go_next_page(page, account_id):
                break

        _log(
            account_id,
            f"本店完成：共 {stats['pages']} 页，扫描 {stats['scanned']} 行，"
            f"跳过(早于门槛) {stats['skipped_old']}，其它跳过 {stats['skipped_other']}，"
            f"{'试运行命中' if settings.dry_run else '实际下架'} {stats['hit']} 条",
        )

    except Exception as e:
        stats["error"] = str(e)
        _log(account_id, f"业务运行报错: {e}")
        try:
            shot_path = _error_screenshot_path(f"error_delist_{account_id}.png")
            page.get_screenshot(path=shot_path)
            _log(account_id, f"已保存报错截图：{shot_path}")
        except Exception:
            pass

    return stats


def random_delay() -> float:
    return random.uniform(1.5, 2.5)


def run_delist_job(config: dict):
    settings = load_delist_settings(config)
    parse_threshold(settings.min_created_after)

    accounts = resolve_target_accounts(config, settings)
    if not accounts:
        print("未选择任何参与下架的店铺")
        return

    print(
        f"\n=== 批量下架任务 ===\n"
        f"门槛时间(严格大于): {settings.min_created_after}\n"
        f"试运行: {settings.dry_run}\n"
        f"单店最多处理: {settings.max_delist_per_run} 条（达到上限、或扫到早于门槛的商品页即停止）\n"
        f"店铺({len(accounts)}): {[a.get('account_id') for a in accounts]}\n"
    )

    all_stats = []
    for idx, account in enumerate(accounts):
        aid = account.get("account_id", "")
        print(f"\n--- 店铺 {idx + 1}/{len(accounts)}: {aid} ---")
        stats = process_account_delist(account, settings)
        all_stats.append(stats)
        if idx < len(accounts) - 1:
            print("\n等待 5 秒后切换下一个店铺...\n")
            time.sleep(5)

    total_hit = sum(s.get("hit", 0) for s in all_stats)
    total_scanned = sum(s.get("scanned", 0) for s in all_stats)
    print(
        f"\n=== 全部店铺完成 ===\n"
        f"共处理 {len(all_stats)} 个店铺，累计扫描 {total_scanned} 行，"
        f"{'试运行命中' if settings.dry_run else '实际下架'} {total_hit} 条\n"
    )
    for s in all_stats:
        aid = s.get("account_id", "?")
        if s.get("error"):
            print(f"  [{aid}] 异常: {s['error']}")
        else:
            print(
                f"  [{aid}] {s.get('pages', 0)} 页 / "
                f"扫描 {s.get('scanned', 0)} / 命中 {s.get('hit', 0)}"
            )
