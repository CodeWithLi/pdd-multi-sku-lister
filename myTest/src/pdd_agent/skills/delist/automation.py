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
import re
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
GOODS_LIST_PAGE_SIZE = 10
DELIST_MERCHANT_CODE_SEARCH_BATCH_SIZE = 5
_LAST_GOODS_LIST_SEARCH_FIELD = ""


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


def _dismiss_pdd_blocking_modals(page, account_id: str, label: str = "商品列表") -> None:
    """关闭拼多多后台常见遮罩（如经营地址补充弹窗），避免挡住后续点击。"""
    from pdd_agent.skills.listing.upload import _dismiss_address_required_page

    for _ in range(3):
        if not _dismiss_address_required_page(page, account_id, label):
            break
        time.sleep(0.6)


def open_goods_list_on_sale(page, account_id: str) -> bool:
    """进入商品列表并切换到「在售中」。"""
    opened = False
    for url in GOODS_LIST_URLS:
        _log(account_id, f"尝试打开商品列表：{url}")
        page.get(url)
        time.sleep(3)
        if "login" in page.url:
            return False
        _dismiss_pdd_blocking_modals(page, account_id)
        if page.ele("text:商品列表", timeout=2) or page.ele("text:创建时间", timeout=2):
            opened = True
            break

    if not opened:
        _log(account_id, "未能确认进入商品列表页，仍将尝试查找表格")
        page.get(GOODS_LIST_URLS[0])
        time.sleep(3)
        _dismiss_pdd_blocking_modals(page, account_id)

    _dismiss_pdd_blocking_modals(page, account_id)
    tab = page.ele("text:在售中", timeout=10)
    if tab:
        try:
            tab.click()
        except Exception:
            _log(account_id, "点击「在售中」被弹窗遮挡，尝试关闭遮罩后重试")
            _dismiss_pdd_blocking_modals(page, account_id)
            tab = page.ele("text:在售中", timeout=10)
            if not tab:
                _log(account_id, "关闭遮罩后仍未找到「在售中」标签")
                return False
            tab.click()
        time.sleep(2)
        _log(account_id, "已切换到「在售中」")
        return True

    _log(account_id, "未找到「在售中」标签，中止（避免误操作其他状态商品）")
    return False


def _get_table_rows(page):
    """定位商品列表数据行（兼容 beast-core-table / tbody）。"""
    best: list = []
    for sel in (
        "css:tr[data-testid='beast-core-table-body-tr']",
        "css:tbody tr",
        "tag:tr",
    ):
        try:
            rows = page.eles(sel, timeout=0.8)
        except Exception:
            rows = []
        filtered = [r for r in rows if _is_goods_list_data_row(r)]
        if len(filtered) > len(best):
            best = filtered
    return best


def _is_goods_list_data_row(row) -> bool:
    text = (row.text or "").strip()
    if not text or "创建时间" in text:
        return False
    if extract_product_id_from_text(text):
        return True
    if "商品编码" in text or "商品ID" in text or "ID:" in text:
        return True
    return len(text) > 40


def _row_passes_merchant_filter(row_text: str, code_filter: str) -> bool:
    if not code_filter:
        return True
    return code_filter in row_text


def _modal_is_open(page) -> bool:
    return bool(_find_delist_modal_root(page))


def _find_delist_modal_root(page):
    """查找可见的下架确认弹层（兼容批量/单条文案差异）。"""
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
            const markers = [
                '确定下架商品', '确定下架所选', '确定批量下架',
                '下架所选商品', '确认下架商品', '确认批量下架',
            ];
            function matchesDelistModal(text) {
                const t = (text || '').replace(/\\s+/g, '');
                if (!t) return false;
                if (markers.some((m) => t.includes(m))) return true;
                return t.includes('下架') && (t.includes('确定') || t.includes('确认')) && t.includes('取消');
            }
            const roots = document.querySelectorAll(
                '[data-testid="beast-core-modal"], .ant-modal-wrap, .ant-modal, '
                + '[class*="MDL_modal"], [class*="MDL_outer"], [class*="modal"], [class*="Modal"], [role="dialog"]'
            );
            for (const el of roots) {
                if (!isVisible(el)) continue;
                if (matchesDelistModal(el.innerText || el.textContent || '')) return el;
            }
            const all = document.querySelectorAll('div, section');
            for (const el of all) {
                if (!isVisible(el)) continue;
                const t = (el.innerText || el.textContent || '').trim();
                if (t.length > 400) continue;
                if (matchesDelistModal(t)) return el;
            }
            return null;
            """
        )
    except Exception:
        return None


def _wait_delist_confirm_modal(page, account_id: str, timeout: int = 20) -> bool:
    """等待下架确认弹窗出现。"""
    for _ in range(timeout):
        if _modal_is_open(page):
            return True
        time.sleep(0.5)
    _log(account_id, "未出现下架确认弹窗")
    try:
        shot = _error_screenshot_path(f"delist_modal_missing_{int(time.time())}.png")
        page.get_screenshot(path=shot, full_page=False)
        _log(account_id, f"已保存调试截图：{shot}")
    except Exception:
        pass
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
                if (!root.innerText) return null;
                const t = root.innerText.replace(/\\s+/g, '');
                if (!t.includes('下架') || !(t.includes('确定') || t.includes('确认'))) return null;
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
            const markers = [
                '确定下架商品', '确定下架所选', '确定批量下架',
                '下架所选商品', '确认下架商品', '确认批量下架',
            ];
            function matchesDelistModal(text) {
                const t = (text || '').replace(/\\s+/g, '');
                if (!t) return false;
                if (markers.some((m) => t.includes(m))) return true;
                return t.includes('下架') && (t.includes('确定') || t.includes('确认')) && t.includes('取消');
            }
            const candidates = document.querySelectorAll(
                '.ant-modal-wrap, .ant-modal, [class*="modal"], [class*="Modal"], [class*="dialog"], [class*="Dialog"], [role="dialog"], [data-testid="beast-core-modal"]'
            );
            for (const el of candidates) {
                if (!isVisible(el)) continue;
                const t = el.innerText || '';
                if (matchesDelistModal(t)) {
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
                if (matchesDelistModal(t)) {
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
        const bodyText = (document.body.innerText || '');
        if (bodyText.includes('下架') && (bodyText.includes('确定') || bodyText.includes('确认'))) {
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
        if not _modal_is_open(page):
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


def _read_goods_merchant_code_filter(page) -> str:
    from pdd_agent.skills.listing.upload import _read_goods_merchant_code_filter as _read

    return _read(page)


def _log_search_result_diagnostics(
    page,
    account_id: str,
    page_rows: list[dict[str, str]],
    expected: set[str],
    *,
    page_num: int,
) -> None:
    """诊断：列出本页每行商品ID/编码，并提示与目标的差异。"""
    if not page_rows:
        return
    filter_value = _read_goods_merchant_code_filter(page)
    if filter_value:
        _log(account_id, f"第 {page_num} 页筛选框当前值：{filter_value[:200]}")
    pagination = _read_pagination_summary(page)
    if pagination:
        _log(account_id, f"第 {page_num} 页分页：{pagination}")

    _log(account_id, f"第 {page_num} 页行内编码明细（共 {len(page_rows)} 行）：")
    for idx, item in enumerate(page_rows, start=1):
        product_id = str(item.get("product_id") or "").strip() or "<无>"
        row_code = str(item.get("merchant_code") or "").strip()
        display_code = row_code.splitlines()[0].strip() if row_code else ""
        if not display_code:
            snippet = re.sub(r"\s+", " ", str(item.get("row_text") or ""))[:80]
            _log(account_id, f"  #{idx} ID={product_id} 商品编码=<未解析> 摘要={snippet}")
            continue
        matched = _match_code_in_row_text(str(item.get("row_text") or ""), expected) or merchant_code_matches_expected(display_code, expected)
        if matched:
            _log(account_id, f"  #{idx} ID={product_id} 商品编码={display_code} → 命中目标")
            continue
        hint = ""
        for target in sorted(expected):
            if display_code.startswith(target) or target.startswith(display_code):
                hint = f"（与目标「{target}」相似但不完全一致，已跳过）"
                break
        _log(account_id, f"  #{idx} ID={product_id} 商品编码={display_code}{hint}")


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


def _normalize_merchant_code_list(codes: list[str]) -> list[str]:
    """多个编码之间可用逗号/空格分隔；单个编码原样保留（不截短、不提取）。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in codes:
        for token in re.split(r"[,，\s]+", str(raw or "")):
            code = token.strip()
            if not code:
                continue
            key = code.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(code)
    return out


def chunk_merchant_codes_for_search(
    codes: list[str],
    *,
    batch_size: int | None = None,
) -> list[list[str]]:
    """将商品编码按批切分，供筛选框空格分隔批量查询。"""
    normalized = _normalize_merchant_code_list(codes)
    if not normalized:
        return []
    size = max(1, int(batch_size or DELIST_MERCHANT_CODE_SEARCH_BATCH_SIZE))
    return [normalized[index : index + size] for index in range(0, len(normalized), size)]


def _search_code_matches_row(row_code: str, search_code: str) -> bool:
    """行内商品编码与搜索编码必须完全一致（不截短、不前缀匹配）。"""
    row_code = str(row_code or "").strip()
    search_code = str(search_code or "").strip()
    return bool(row_code and search_code and row_code == search_code)


def extract_merchant_code_from_row_text(row_text: str) -> str:
    """从商品信息列解析「商品编码: xxx」，只取标签后第一个编码 token（不含换行/空格）。"""
    text = str(row_text or "")
    match = re.search(r"商品编码[：:=]\s*([^\s\n\r]+)", text)
    if match:
        return match.group(1).strip()
    return ""


def extract_spec_codes_from_row_text(row_text: str) -> list[str]:
    """从行文本解析「规格编码: xxx」（可能有多个）。"""
    text = str(row_text or "")
    codes: list[str] = []
    for match in re.finditer(r"规格编码[：:=]\s*([^\s\n\r]+)", text):
        code = str(match.group(1) or "").strip()
        if code and code not in codes:
            codes.append(code)
    return codes


def match_row_merchant_code(
    row_text: str,
    expected_codes: set[str],
    *,
    allow_spec_filter_match: bool = False,
) -> str:
    """按行内「商品编码」或「规格编码」精确匹配目标编码（字符级相等）。"""
    if not expected_codes:
        return ""
    product_code = extract_merchant_code_from_row_text(row_text)
    if product_code and product_code in expected_codes:
        return product_code
    for spec_code in extract_spec_codes_from_row_text(row_text):
        if spec_code in expected_codes:
            return spec_code
    return ""


def goods_list_search_field() -> str:
    return str(_LAST_GOODS_LIST_SEARCH_FIELD or "").strip()


def _goods_list_table_loading(page) -> bool:
    try:
        return bool(
            page.run_js(
                """
                const text = (document.body?.innerText || '').replace(/\\s+/g, '');
                if (text.includes('加载中') || text.includes('正在加载')) return true;
                for (const el of document.querySelectorAll('[class*="loading"], [class*="Loading"], [class*="spin"]')) {
                    const s = window.getComputedStyle(el);
                    if (s.display === 'none' || s.visibility === 'hidden') continue;
                    const r = el.getBoundingClientRect();
                    if (r.width > 8 && r.height > 8) return true;
                }
                return false;
                """
            )
        )
    except Exception:
        return False


def _goods_list_empty_state(page) -> bool:
    try:
        return bool(
            page.run_js(
                """
                const text = (document.body?.innerText || '').replace(/\\s+/g, '');
                const markers = ['暂无数据', '没有找到', '无符合条件', '未找到相关商品', '暂无商品'];
                return markers.some((m) => text.includes(m));
                """
            )
        )
    except Exception:
        return False


def _wait_goods_list_search_settled(page, account_id: str, *, timeout: float = 20.0) -> str:
    """等待商品列表搜索刷新。返回 ready / empty / timeout。"""
    deadline = time.time() + timeout
    last_count = -1
    stable = 0
    while time.time() < deadline:
        if _goods_list_table_loading(page):
            time.sleep(0.35)
            continue
        if _goods_list_empty_state(page):
            return "empty"
        rows = _get_table_rows(page)
        count = len(rows)
        if count > 0:
            if count == last_count:
                stable += 1
                if stable >= 2:
                    return "ready"
            else:
                stable = 0
            last_count = count
        time.sleep(0.45)
    if _goods_list_empty_state(page):
        return "empty"
    return "ready" if _get_table_rows(page) else "timeout"


def _search_has_matching_rows(page, codes: list[str], *, filter_label: str) -> bool:
    expected = {str(code or "").strip() for code in codes if str(code or "").strip()}
    if not expected:
        return False
    rows = _scan_filtered_rows_on_page(page)
    if not rows:
        return False
    for item in rows:
        row_text = str(item.get("row_text") or "")
        if match_row_merchant_code(row_text, expected):
            return True
    return False


def verify_row_safe_to_delist(
    row,
    *,
    product_id: str,
    matched_code: str,
    expected_codes: set[str],
    known_product_ids: set[str] | None = None,
) -> tuple[bool, str]:
    """
    点击「下架」前二次校验：行内商品编码必须与目标编码完全一致（字符级相等）。
    product_id 仅用于确认操作的是同一行，不限制「同编码多链接」是否下架。
    """
    _ = known_product_ids
    product_id = str(product_id or "").strip()
    matched_code = str(matched_code or "").strip()
    if not product_id or not matched_code:
        return False, "missing_product_id_or_code"

    text = ""
    try:
        text = row.text or ""
    except Exception:
        return False, "row_unreadable"

    row_pid = str(extract_product_id_from_text(text) or "").strip()
    if row_pid != product_id:
        return False, f"product_id_mismatch:{row_pid}!={product_id}"

    if goods_list_search_field() == "规格编码":
        spec_codes = extract_spec_codes_from_row_text(text)
        if matched_code in spec_codes:
            return True, "ok"
        return False, f"spec_code_mismatch:expected={matched_code},row={spec_codes}"

    row_matched = _match_code_in_row_text(text, {matched_code})
    if not row_matched:
        row_code = extract_merchant_code_from_row_text(text)
        if not row_code:
            return False, "merchant_code_unparsed"
        return False, f"merchant_code_mismatch:{row_code}!={matched_code}"
    if row_matched != matched_code:
        return False, f"merchant_code_mismatch:{row_matched}!={matched_code}"
    if matched_code not in expected_codes:
        return False, f"code_not_in_expected:{matched_code}"

    return True, "ok"


def merchant_code_matches_expected(row_code: str, expected_codes: set[str]) -> str:
    """勾选前校验：行内商品编码须与目标编码完全一致。"""
    row_code = str(row_code or "").strip()
    if not row_code or not expected_codes:
        return ""
    if row_code in expected_codes:
        return row_code
    return ""


def _match_code_in_row_text(row_text: str, expected_codes: set[str]) -> str:
    return match_row_merchant_code(row_text, expected_codes)


def _match_merchant_code_in_row(row_text: str, merchant_codes: list[str]) -> str:
    """行文本匹配商品编码（商品编码 / 规格编码）。"""
    expected = {str(c or "").strip() for c in merchant_codes if str(c or "").strip()}
    return _match_code_in_row_text(row_text, expected)


def _scan_filtered_rows_on_page(page) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in _get_table_rows(page):
        text = row.text or ""
        product_id = str(extract_product_id_from_text(text) or "").strip()
        if not product_id:
            continue
        rows.append(
            {
                "product_id": product_id,
                "row_text": text,
                "merchant_code": extract_merchant_code_from_row_text(text),
                "row": row,
            }
        )
    return rows


def _row_checkbox_is_checked(row) -> bool:
    try:
        return bool(
            row.run_js(
                """
                const tr = arguments[0];
                if (!tr) return false;
                const input = tr.querySelector('input[type="checkbox"]');
                if (input) return !!input.checked;
                const aria = tr.querySelector('[aria-checked="true"], [data-checked="true"]');
                if (aria) return true;
                const icon = tr.querySelector('[data-testid="beast-core-checkbox-checkIcon"], [class*="CBX_active"]');
                return !!icon;
                """,
                row,
            )
        )
    except Exception:
        return False


def _click_row_checkbox(page, row) -> bool:
    if _row_checkbox_is_checked(row):
        return True
    try:
        clicked = page.run_js(
            """
            const tr = arguments[0];
            if (!tr) return false;
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none' && s.visibility !== 'hidden';
            }
            function tryClick(el) {
                if (!el || !isVisible(el)) return false;
                try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
                el.click();
                return true;
            }
            const cell = tr.querySelector('td[class*="checkCell"], td[class*="CheckCell"], td:first-child') || tr;
            const targets = [
                cell.querySelector('label[class*="CBX"]'),
                cell.querySelector('[data-testid="beast-core-checkbox"]'),
                cell.querySelector('input[type="checkbox"]'),
                cell.querySelector('label'),
                cell,
            ];
            for (const el of targets) {
                if (tryClick(el)) return true;
            }
            return false;
            """,
            row,
        )
        if not clicked:
            return False
        time.sleep(0.15)
        if _row_checkbox_is_checked(row):
            return True
        # 部分页面需双击或点 label 内层
        page.run_js(
            """
            const tr = arguments[0];
            const label = tr.querySelector('label[class*="CBX"]');
            if (label) label.click();
            """,
            row,
        )
        time.sleep(0.15)
        return _row_checkbox_is_checked(row)
    except Exception:
        return False


def _count_checked_rows_on_page(page) -> int:
    try:
        count = page.run_js(
            """
            const rows = Array.from(document.querySelectorAll('tbody tr'));
            let n = 0;
            for (const tr of rows) {
                const input = tr.querySelector('input[type="checkbox"]');
                if (input && input.checked) { n++; continue; }
                if (tr.querySelector('[aria-checked="true"], [data-checked="true"], [data-testid="beast-core-checkbox-checkIcon"]')) {
                    n++;
                }
            }
            return n;
            """
        )
        return int(count or 0)
    except Exception:
        return 0


def _read_selection_bar_count(page) -> int:
    """读取底部「已选 N 条/件」计数。"""
    try:
        count = page.run_js(
            """
            const text = document.body.innerText || '';
            const patterns = [
                /已选(?:中)?\\s*(\\d+)\\s*(?:条|件|个)/,
                /已选择\\s*(\\d+)\\s*(?:条|件|个)/,
                /共选(?:中)?\\s*(\\d+)\\s*(?:条|件|个)/,
            ];
            for (const re of patterns) {
                const m = text.match(re);
                if (m) return parseInt(m[1], 10);
            }
            return 0;
            """
        )
        return int(count or 0)
    except Exception:
        return 0


def _delist_row_via_action_link(
    page,
    row,
    account_id: str,
    product_id: str,
    *,
    matched_code: str = "",
    expected_codes: set[str] | None = None,
    known_product_ids: set[str] | None = None,
) -> bool:
    """对单行点击「下架」并确认；点击前须通过精准校验。"""
    if expected_codes and matched_code:
        ok, reason = verify_row_safe_to_delist(
            row,
            product_id=product_id,
            matched_code=matched_code,
            expected_codes=expected_codes,
            known_product_ids=known_product_ids,
        )
        if not ok:
            _log(
                account_id,
                f"  下架中止 ID={product_id} 商品编码={matched_code}（校验未通过：{reason}）",
            )
            return False
    try:
        link = row.ele("text:下架", timeout=2)
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
                    if (t !== '下架' || !isVisible(n)) continue;
                    try { n.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
                    n.click();
                    return true;
                }
                return false;
                """,
                row,
            )
            if not clicked:
                _log(account_id, f"  行内未找到「下架」链接 ID={product_id}")
                return False
        time.sleep(0.8)
        if _confirm_delist_dialog(page, account_id, product_id):
            return True
        _dismiss_delist_modal(page, account_id)
        return False
    except Exception as exc:
        _log(account_id, f"  行内下架异常 ID={product_id}: {exc}")
        return False


def _execute_batch_delist_for_selection(
    page,
    account_id: str,
    *,
    sample_product_id: str,
    checked_count: int,
    checked_rows: list[dict[str, object]] | None = None,
    dry_run: bool,
) -> tuple[int, str]:
    if checked_count <= 0:
        return 0, ""
    if dry_run:
        _log(account_id, f"[试运行] 本页已勾选 {checked_count} 条，将点击批量下架")
        return checked_count, ""

    ui_checked = max(_count_checked_rows_on_page(page), _read_selection_bar_count(page))
    if ui_checked < checked_count:
        _log(
            account_id,
            f"勾选未完全生效（预期 {checked_count}，页面 {ui_checked}），改为逐条下架",
        )
        return _delist_checked_rows_one_by_one(page, account_id, checked_rows or [])

    if not _click_batch_delist_toolbar(page, account_id):
        _log(account_id, "未找到可用的「批量下架」按钮，改为逐条下架")
        return _delist_checked_rows_one_by_one(page, account_id, checked_rows or [])

    time.sleep(1.0)
    if not _confirm_delist_dialog(page, account_id, sample_product_id):
        _dismiss_delist_modal(page, account_id)
        _log(account_id, "批量下架确认失败，改为逐条下架")
        return _delist_checked_rows_one_by_one(page, account_id, checked_rows or [])

    _log(account_id, f"本页批量下架成功 {checked_count} 条")
    time.sleep(1.5)
    return checked_count, ""


def _delist_checked_rows_one_by_one(
    page,
    account_id: str,
    checked_rows: list[dict[str, object]],
) -> tuple[int, str]:
    """批量下架失败时，对目标行逐条点「下架」（每步重新定位行，避免 DOM 失效）。"""
    pending_ids = list(
        dict.fromkeys(
            str(item.get("product_id") or "").strip()
            for item in checked_rows
            if str(item.get("product_id") or "").strip()
        )
    )
    meta_by_id = {
        str(item.get("product_id") or "").strip(): item
        for item in checked_rows
        if str(item.get("product_id") or "").strip()
    }
    delisted = 0
    for product_id in pending_ids:
        meta = meta_by_id.get(product_id) or {}
        row_code = str(meta.get("merchant_code") or "").strip()
        page_rows = _scan_filtered_rows_on_page(page)
        row_data = next(
            (r for r in page_rows if str(r.get("product_id") or "").strip() == product_id),
            None,
        )
        if not row_data or not row_data.get("row"):
            _log(account_id, f"  逐条下架跳过 ID={product_id}（列表中未找到，可能已下架）")
            delisted += 1
            continue
        _log(account_id, f"  逐条下架 ID={product_id} 商品编码={row_code}")
        if _delist_row_via_action_link(page, row_data["row"], account_id, product_id):
            delisted += 1
            time.sleep(1.0)
        else:
            _log(account_id, f"  逐条下架失败 ID={product_id}")
    if delisted <= 0:
        return 0, "confirm_batch_delist_failed"
    return delisted, ""


def batch_delist_by_verified_checkboxes(
    page,
    account_id: str,
    merchant_codes: list[str],
    *,
    dry_run: bool = False,
    page_size: int = GOODS_LIST_PAGE_SIZE,
    known_product_ids_by_code: dict[str, set[str]] | None = None,
) -> dict[str, object]:
    """
    整合链路上架前下架：搜索框填入本批编码（空格分隔）→ 逐页逐行校验编码 → 逐条下架。

    安全策略：
    - 行内商品编码须与目标编码字符级完全一致
    - 同编码多链接：编码一致即下架，不校验本地商品 ID
    """
    expected_list = _normalize_merchant_code_list(merchant_codes)
    expected = set(expected_list)
    if not expected:
        return {
            "ok": False,
            "filter_error": "missing_merchant_codes",
            "total_checked": 0,
            "total_delisted": 0,
            "pages_processed": 0,
            "delisted_items": [],
            "found_codes": [],
            "missing_codes": [],
            "errors": ["missing_merchant_codes"],
        }

    _log(
        account_id,
        f"本批下架：{len(expected_list)} 个编码已搜索，逐页匹配（编码完全一致才下架）",
    )

    total_delisted = 0
    delisted_items: list[dict[str, str]] = []
    errors: list[str] = []
    pages_processed = 0
    found_codes: set[str] = set()
    skipped_non_target = 0

    for page_num in range(1, MAX_PAGES + 1):
        page_rows = _scan_filtered_rows_on_page(page)
        if not page_rows:
            _log(account_id, f"第 {page_num} 页无数据，分页下架结束")
            break

        targets: list[dict[str, str]] = []
        _log(account_id, f"第 {page_num} 页共 {len(page_rows)} 行，开始逐行校验")
        for item in page_rows:
            row_text = str(item.get("row_text") or "")
            matched_code = _match_code_in_row_text(row_text, expected)
            if not matched_code:
                row_code = str(item.get("merchant_code") or "").strip()
                matched_code = merchant_code_matches_expected(row_code, expected)
            if not matched_code:
                skipped_non_target += 1
                continue
            product_id = str(item.get("product_id") or "").strip()
            found_codes.add(matched_code)
            row_code = str(item.get("merchant_code") or "").strip() or extract_merchant_code_from_row_text(row_text)
            targets.append(
                {
                    "product_id": product_id,
                    "merchant_code": row_code,
                    "matched_code": matched_code,
                }
            )
            _log(
                account_id,
                f"  搜索命中 ID={item.get('product_id')} 商品编码={matched_code}",
            )

        if targets:
            _log(account_id, f"第 {page_num} 页命中 {len(targets)} 条目标商品，开始逐条下架")
        else:
            _log(account_id, f"第 {page_num} 页无目标商品（已跳过 {len(page_rows)} 行）")
            _log_search_result_diagnostics(page, account_id, page_rows, expected, page_num=page_num)

        pages_processed = page_num

        for target in targets:
            product_id = str(target.get("product_id") or "").strip()
            matched_code = str(target.get("matched_code") or "").strip()
            if not product_id:
                continue
            if dry_run:
                delisted_items.append(
                    {
                        "product_id": product_id,
                        "merchant_code": target.get("merchant_code", ""),
                        "matched_code": matched_code,
                    }
                )
                total_delisted += 1
                continue

            fresh_rows = _scan_filtered_rows_on_page(page)
            row_data = next(
                (r for r in fresh_rows if str(r.get("product_id") or "").strip() == product_id),
                None,
            )
            if not row_data or not row_data.get("row"):
                msg = f"delist_row_not_found:{product_id}"
                errors.append(msg)
                _log(account_id, f"  下架前未找到行 ID={product_id} 商品编码={matched_code}")
                continue

            ok, reason = verify_row_safe_to_delist(
                row_data["row"],
                product_id=product_id,
                matched_code=matched_code,
                expected_codes=expected,
            )
            if not ok:
                _log(
                    account_id,
                    f"  下架中止 ID={product_id} 商品编码={matched_code}（二次校验：{reason}）",
                )
                errors.append(f"verify_failed:{product_id}:{reason}")
                continue

            _log(account_id, f"  精准下架 ID={product_id} 商品编码={matched_code}")
            if _delist_row_via_action_link(
                page,
                row_data["row"],
                account_id,
                product_id,
                matched_code=matched_code,
                expected_codes=expected,
            ):
                total_delisted += 1
                delisted_items.append(
                    {
                        "product_id": product_id,
                        "merchant_code": str(target.get("merchant_code") or ""),
                        "matched_code": matched_code,
                    }
                )
                time.sleep(0.8)
            else:
                msg = f"delist_failed:{product_id}"
                errors.append(msg)
                _log(account_id, f"  下架失败 ID={product_id} 商品编码={matched_code}")

        if len(page_rows) < page_size:
            _log(account_id, f"第 {page_num} 页不足 {page_size} 行，已是最后一页")
            break
        if not _go_next_page(page, account_id):
            break

    missing_codes = sorted(expected - found_codes)
    if found_codes:
        _log(
            account_id,
            f"搜索命中 {len(found_codes)}/{len(expected)} 个编码：{', '.join(sorted(found_codes))}",
        )
    else:
        _log(account_id, "搜索未命中任何目标编码（请核对拼多多商品编码是否与文件夹名完全一致）")
    if missing_codes:
        _log(
            account_id,
            f"搜索未命中 {len(missing_codes)} 个编码（可能未在售或编码不一致）：{', '.join(missing_codes)}",
        )
    if skipped_non_target:
        _log(account_id, f"已跳过 {skipped_non_target} 行非目标商品（编码不一致）")
    _log(
        account_id,
        f"分页下架完成：搜索命中 {len(found_codes)} 个编码，成功下架 {total_delisted} 条，"
        f"处理 {pages_processed} 页",
    )

    return {
        "ok": not errors,
        "filter_error": "",
        "total_checked": total_delisted,
        "total_delisted": total_delisted,
        "pages_processed": pages_processed,
        "delisted_items": delisted_items,
        "found_codes": sorted(found_codes),
        "missing_codes": missing_codes,
        "errors": errors,
    }


def scan_filtered_product_rows_all_pages(
    page,
    account_id: str,
    *,
    merchant_codes: list[str] | None = None,
) -> list[dict[str, str]]:
    """在当前筛选结果下翻页扫描全部商品行。"""
    codes = [str(c or "").strip() for c in (merchant_codes or []) if str(c or "").strip()]
    found: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for page_num in range(1, MAX_PAGES + 1):
        page_rows = _scan_filtered_rows_on_page(page)
        _log(account_id, f"商品列表第 {page_num} 页，扫描 {len(page_rows)} 行")
        if not page_rows:
            break
        for item in page_rows:
            product_id = item["product_id"]
            if product_id in seen_ids:
                continue
            seen_ids.add(product_id)
            row_text = item.get("row_text") or ""
            merchant_code = _match_merchant_code_in_row(row_text, codes) if codes else ""
            found.append(
                {
                    "product_id": product_id,
                    "merchant_code": merchant_code,
                    "row_text": row_text,
                }
            )
        if not _go_next_page(page, account_id):
            break
    return found


def _click_goods_table_select_all(page) -> bool:
    clicked = page.run_js(
        """
        function isVisible(el) {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 2 && r.height > 2
                && s.display !== 'none' && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }
        function clickEl(el) {
            el.scrollIntoView({ block: 'center', inline: 'nearest' });
            el.click();
            return true;
        }
        const table = document.querySelector('table') || document.body;
        const headerCell = Array.from(table.querySelectorAll('thead th, thead td, th'))
            .find((el) => isVisible(el) && el.querySelector('input[type="checkbox"], [role="checkbox"], label'));
        if (headerCell) {
            const box = headerCell.querySelector('input[type="checkbox"], [role="checkbox"], label, span');
            if (box && clickEl(box)) return true;
            if (clickEl(headerCell)) return true;
        }
        const boxes = Array.from(document.querySelectorAll('thead input[type="checkbox"], thead [role="checkbox"]'))
            .filter(isVisible);
        if (boxes[0]) return clickEl(boxes[0]);
        return false;
        """
    )
    return bool(clicked)


def _click_batch_delist_toolbar(page, account_id: str = "") -> bool:
    try:
        clicked = page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none' && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            function isEnabled(el) {
                if (!el) return false;
                if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
                const cls = (el.className || '') + '';
                if (/disabled|Disabled/.test(cls)) return false;
                return true;
            }
            function clickEl(el) {
                try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
                el.click();
                return true;
            }
            const candidates = [];
            for (const el of document.querySelectorAll('button, a, span, div')) {
                if (!isVisible(el) || !isEnabled(el)) continue;
                const t = (el.innerText || el.textContent || '').trim();
                if (t !== '批量下架' && !/^批量下架\\s*\\(?\\d*/.test(t)) continue;
                let score = 0;
                let p = el;
                for (let i = 0; i < 10 && p; i++) {
                    const pt = (p.innerText || p.textContent || '');
                    if (/已选|已选择|共选/.test(pt)) score += 10;
                    if (p.getBoundingClientRect().bottom > window.innerHeight - 180) score += 5;
                    p = p.parentElement;
                }
                candidates.push({ el, score });
            }
            candidates.sort((a, b) => b.score - a.score);
            if (candidates[0]) {
                clickEl(candidates[0].el);
                return candidates[0].score >= 10 ? 'selection_bar' : 'toolbar';
            }
            return null;
            """
        )
        if clicked:
            if account_id:
                _log(account_id, f"已点击「批量下架」（{clicked}）")
            return True
    except Exception:
        pass
    for sel in (
        "text:批量下架",
        'xpath://button[contains(normalize-space(.),"批量下架")]',
        'xpath://a[contains(normalize-space(.),"批量下架")]',
    ):
        btn = page.ele(sel, timeout=2)
        if btn:
            try:
                btn.click()
                if account_id:
                    _log(account_id, "已点击「批量下架」（元素定位）")
                return True
            except Exception:
                continue
    if account_id:
        _log(account_id, "未找到「批量下架」按钮")
    return False


def _batch_delist_current_page(page, account_id: str, *, dry_run: bool = False) -> tuple[int, str]:
    rows = _scan_filtered_rows_on_page(page)
    count = len(rows)
    if count <= 0:
        return 0, ""
    if dry_run:
        _log(account_id, f"[试运行] 本页 {count} 条将批量下架")
        return count, ""

    if not _click_goods_table_select_all(page):
        return 0, "select_all_failed"
    time.sleep(0.5)
    if not _click_batch_delist_toolbar(page, account_id):
        return 0, "batch_delist_button_not_found"
    time.sleep(0.8)
    sample_id = rows[0]["product_id"]
    if not _confirm_delist_dialog(page, account_id, sample_id):
        _dismiss_delist_modal(page, account_id)
        return 0, "confirm_batch_delist_failed"
    _log(account_id, f"本页批量下架成功 {count} 条")
    time.sleep(1.2)
    return count, ""


def batch_delist_filtered_goods(
    page,
    account_id: str,
    *,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """在当前筛选结果下逐页全选并批量下架。"""
    total = 0
    errors: list[str] = []
    stagnant_rounds = 0
    for round_idx in range(1, MAX_PAGES + 1):
        rows = _scan_filtered_rows_on_page(page)
        if not rows:
            break
        hit, err = _batch_delist_current_page(page, account_id, dry_run=dry_run)
        if err:
            errors.append(err)
            break
        if hit <= 0:
            stagnant_rounds += 1
            if stagnant_rounds >= 2:
                break
            time.sleep(1)
            continue
        stagnant_rounds = 0
        total += hit
        _log(account_id, f"批量下架累计 {total} 条（第 {round_idx} 轮）")
        time.sleep(1)
    return total, errors


def filter_goods_by_merchant_codes(
    page,
    account_id: str,
    merchant_codes: list[str],
    *,
    try_spec_code_search: bool = False,
) -> bool:
    from pdd_agent.skills.listing.upload import (
        _click_goods_search as click_search,
        _fill_goods_merchant_code_filter,
    )

    global _LAST_GOODS_LIST_SEARCH_FIELD

    codes = _normalize_merchant_code_list(merchant_codes)
    if not codes:
        return False
    filter_value = " ".join(codes)

    def _run_query(filter_label: str, *, filled: bool, filled_value: str, method: str) -> bool:
        if not filled:
            return False
        _LAST_GOODS_LIST_SEARCH_FIELD = filter_label
        _log(
            account_id,
            f"{filter_label}已写入筛选框：{filled_value[:200]}（{method}）",
        )
        search_result = click_search(page)
        if not search_result.get("clicked"):
            _log(account_id, f"未点击到「查询」按钮（{filter_label}），中止本编码搜索")
            return False
        _log(account_id, f"已点击「查询」按钮（{search_result.get('method')}）")
        state = _wait_goods_list_search_settled(page, account_id)
        row_count = len(_get_table_rows(page))
        _log(
            account_id,
            f"已执行{filter_label}搜索（{len(codes)} 个）：{filter_value[:200]}；"
            f"列表状态={state}，可见行={row_count}",
        )
        if state == "empty" or row_count <= 0:
            return False
        if _search_has_matching_rows(page, codes, filter_label=filter_label):
            return True
        _log_search_result_diagnostics(page, account_id, _scan_filtered_rows_on_page(page), set(codes), page_num=1)
        return False

    _clear_goods_filters(page)
    fill_result = _fill_goods_merchant_code_filter(page, filter_value)
    if _run_query(
        "商品编码",
        filled=bool(fill_result.get("filled")),
        filled_value=str(fill_result.get("value") or filter_value),
        method=str(fill_result.get("method") or ""),
    ):
        return True

    if not try_spec_code_search:
        _LAST_GOODS_LIST_SEARCH_FIELD = ""
        _log(account_id, f"商品编码未搜索到（未开启规格编码搜索）：{filter_value[:200]}")
        return False

    _log(account_id, f"商品编码搜索无命中，尝试按「规格编码」搜索：{filter_value[:200]}")
    _clear_goods_filters(page)
    from pdd_agent.skills.listing.upload import _fill_goods_spec_code_filter

    spec_fill = _fill_goods_spec_code_filter(page, filter_value)
    if _run_query(
        "规格编码",
        filled=bool(spec_fill.get("filled")),
        filled_value=str(spec_fill.get("value") or filter_value),
        method=str(spec_fill.get("method") or ""),
    ):
        return True

    _LAST_GOODS_LIST_SEARCH_FIELD = ""
    _log(account_id, f"商品编码与规格编码均未搜索到：{filter_value[:200]}")
    return False


def filter_goods_by_product_ids(page, account_id: str, product_ids: list[str]) -> bool:
    global _LAST_GOODS_LIST_SEARCH_FIELD
    from pdd_agent.skills.listing.upload import (
        _click_goods_search as click_search,
        _fill_goods_id_filter,
        _read_goods_id_filter,
    )

    ids = [str(pid or "").strip() for pid in product_ids if str(pid or "").strip()]
    if not ids:
        return False
    filter_value = " ".join(ids)
    _clear_goods_filters(page)
    fill_result = _fill_goods_id_filter(page, filter_value)
    if not fill_result.get("filled"):
        current = _read_goods_id_filter(page)
        _log(
            account_id,
            f"商品ID筛选框写入失败（期望 {filter_value[:120]}，当前 {current[:120]}）",
        )
        return False
    _LAST_GOODS_LIST_SEARCH_FIELD = "商品ID"
    search_result = click_search(page)
    if not search_result.get("clicked"):
        _log(account_id, "未点击到「查询」按钮，商品ID筛选可能未生效")
        return False
    _log(
        account_id,
        f"商品ID已写入筛选框：{str(fill_result.get('value') or filter_value)[:120]}"
        f"（{fill_result.get('method')}）",
    )
    _log(account_id, f"已点击「查询」按钮（{search_result.get('method')}）")
    state = _wait_goods_list_search_settled(page, account_id)
    row_count = len(_get_table_rows(page))
    _log(account_id, f"已按 {len(ids)} 个商品ID筛选；列表状态={state}，可见行={row_count}")
    if state == "empty" or row_count <= 0:
        return False
    expected = set(ids)
    for item in _scan_filtered_rows_on_page(page):
        row_pid = str(item.get("product_id") or "").strip()
        if row_pid in expected:
            return True
    _log(account_id, f"商品ID筛选后未找到目标行：{filter_value[:120]}")
    return False


def process_single_product_delist(
    page,
    account_config: dict,
    *,
    product_id: str,
    mapping_id: str = "",
    merchant_code: str = "",
    dry_run: bool = False,
    list_already_open: bool = False,
) -> dict:
    """精准下架：优先按商品编码搜索；有商品ID时须行内 ID 与编码同时匹配才下架。"""
    account_id = account_config.get("account_id", "")
    product_id = (product_id or "").strip()
    merchant_code = str(merchant_code or "").strip()
    stats = {
        "account_id": account_id,
        "mapping_id": mapping_id,
        "target_product_id": product_id,
        "merchant_code": merchant_code,
        "scanned": 0,
        "hit": 0,
        "dry_run": dry_run,
    }
    if not product_id and not merchant_code:
        stats["error"] = "missing_product_id_and_merchant_code"
        return stats

    try:
        global _LAST_GOODS_LIST_SEARCH_FIELD

        label = f"商品编码={merchant_code}" if merchant_code else f"商品ID={product_id}"
        _log(account_id, f"开始精准下架 {label}")
        if not list_already_open:
            if not open_goods_list_on_sale(page, account_id):
                stats["error"] = "open_list_failed"
                return stats

        _clear_goods_filters(page)
        if merchant_code:
            from pdd_agent.skills.listing.upload import _fill_goods_merchant_code_filter

            fill_result = _fill_goods_merchant_code_filter(page, merchant_code)
            if not fill_result.get("filled"):
                stats["error"] = "set_merchant_code_filter_failed"
                return stats
            _LAST_GOODS_LIST_SEARCH_FIELD = "商品编码"
        elif product_id:
            from pdd_agent.skills.listing.upload import _fill_goods_id_filter

            fill_result = _fill_goods_id_filter(page, product_id)
            if not fill_result.get("filled"):
                stats["error"] = "set_product_id_filter_failed"
                return stats
            _LAST_GOODS_LIST_SEARCH_FIELD = "商品ID"
        _click_goods_search(page)
        _wait_goods_list_search_settled(page, account_id)

        rows = _get_table_rows(page)
        stats["scanned"] = len(rows)
        row = None
        if product_id:
            row = _find_exact_product_row(page, product_id)
        elif merchant_code:
            for candidate in _scan_filtered_rows_on_page(page):
                row_text = str(candidate.get("row_text") or "")
                if merchant_code_matches_expected(
                    extract_merchant_code_from_row_text(row_text),
                    {merchant_code},
                ):
                    row = candidate.get("row")
                    product_id = str(candidate.get("product_id") or "").strip()
                    break
        if not row:
            stats["error"] = "product_id_not_found_on_sale"
            _log(account_id, f"在售中未找到目标：{label}")
            return stats

        text = row.text or ""
        matched_id = extract_product_id_from_text(text) or ""
        if product_id and matched_id != product_id:
            stats["error"] = f"product_id_mismatch:{matched_id}"
            return stats
        if merchant_code:
            row_code = extract_merchant_code_from_row_text(text)
            if row_code != merchant_code:
                stats["error"] = f"merchant_code_mismatch:{row_code}!={merchant_code}"
                _log(account_id, f"行内商品编码={row_code} 与目标 {merchant_code} 不一致，中止下架")
                return stats
            stats["merchant_code"] = row_code
        stats["target_product_id"] = product_id or matched_id

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
