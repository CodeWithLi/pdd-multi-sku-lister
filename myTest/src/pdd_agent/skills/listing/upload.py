"""多规格上架页面操作（Playwright + DrissionPage 兼容层）。"""

from __future__ import annotations

import random
import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.domain.models import ListingUnit
from pdd_agent.paths import PROJECT_ROOT
from pdd_agent.skills.listing.multi_spec_page import (
    _safe_exc,
    add_style_and_model_specs,
    fill_multi_spec_rows,
    wait_multi_sku_rows,
)
from pdd_agent.skills.listing.page_ai_title import apply_title_after_cover_upload
from pdd_agent.skills.listing.title import resolve_listing_title


def _error_screenshot_path(filename: str) -> str:
    d = PROJECT_ROOT / "data" / "runs" / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / filename)


def _clear_beforeunload(page: DpPage) -> None:
    try:
        page.run_js("window.onbeforeunload = null;")
    except Exception:
        pass


def _listing_result(
    *,
    unit: ListingUnit,
    status: str,
    reason: str = "",
    error: str = "",
    title: str = "",
    retryable: bool = False,
    legacy_status: str = "",
) -> dict[str, Any]:
    return {
        "listing_label": unit.listing_label,
        "product_code": unit.product_code,
        "image_set": unit.image_set,
        "merchant_code": unit.merchant_code,
        "status": status,
        "retryable": retryable,
        "reason": reason,
        "error": error,
        "title": title,
        "legacy_status": legacy_status or status,
    }


def _classify_exception(exc: Exception) -> tuple[str, bool]:
    err = _safe_exc(exc)
    low = err.lower()
    if any(k in err for k in ("验证码", "滑块", "登录", "扫码", "短信")):
        return "needs_manual_login_or_captcha", True
    if any(k in err for k in ("分类", "类目", "SKU", "规格", "预览图", "上传")):
        return "page_or_material_changed", True
    if "timeout" in low or "超时" in err or "disconnect" in low or "连接已断开" in err:
        return "browser_transient_error", True
    return "unexpected_error", False


def _dismiss_address_required_page(page: DpPage, account_id: str, label: str) -> bool:
    """
    拼多多偶尔会在发布页弹出「请尽快填写真实有效联系/经营地址」遮罩。
    这个弹窗没有明显弹窗关闭按钮，会挡住后续分类/上传操作；按页面左上角
    「发布新商品」前的关闭 X 退出当前发布页。
    """
    try:
        result = page.run_js(
            """
            const bodyText = document.body?.innerText || '';
            const present = bodyText.includes('真实有效')
                && (bodyText.includes('联系/经营地址') || bodyText.includes('经营地址'))
                && bodyText.includes('确认补充');
            if (!present) return { present: false, clicked: false };

            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }

            function clickableParent(el) {
                let cur = el;
                for (let i = 0; i < 5 && cur && cur !== document.body; i++) {
                    const tag = (cur.tagName || '').toLowerCase();
                    const role = cur.getAttribute?.('role') || '';
                    const cls = cur.className ? String(cur.className) : '';
                    const cursor = window.getComputedStyle(cur).cursor;
                    if (tag === 'button' || tag === 'a' || role === 'button'
                        || cursor === 'pointer' || cls.toLowerCase().includes('close')) {
                        return cur;
                    }
                    cur = cur.parentElement;
                }
                return el;
            }

            const candidates = [];
            for (const el of document.querySelectorAll('button,a,span,i,svg,div')) {
                if (!isVisible(el)) continue;
                const r = el.getBoundingClientRect();
                if (r.left > 130 || r.top > 190 || r.top < 20) continue;
                const text = (el.innerText || el.textContent || '').trim();
                const aria = el.getAttribute?.('aria-label') || '';
                const cls = el.className ? String(el.className) : '';
                if (
                    text === '×'
                    || text === '✕'
                    || text.includes('发布新商品')
                    || aria.toLowerCase().includes('close')
                    || cls.toLowerCase().includes('close')
                ) {
                    candidates.push({ el, score: r.left + r.top });
                }
            }
            candidates.sort((a, b) => a.score - b.score);
            if (candidates.length) {
                clickableParent(candidates[0].el).click();
                return { present: true, clicked: true, method: 'candidate' };
            }

            for (const [x, y] of [[50, 80], [50, 110], [50, 140], [65, 80], [65, 110]]) {
                const el = document.elementFromPoint(x, y);
                if (el && isVisible(el)) {
                    clickableParent(el).click();
                    return { present: true, clicked: true, method: 'point' };
                }
            }
            return { present: true, clicked: false };
            """
        )
        if not isinstance(result, dict) or not result.get("present"):
            return False

        if result.get("clicked"):
            print(
                f"[{account_id}] [{label}] 检测到经营地址补充弹窗，已点击左上角关闭发布页",
                flush=True,
            )
            time.sleep(1)
            _confirm_leave_publish_page(page)
        else:
            print(
                f"[{account_id}] [{label}] 检测到经营地址补充弹窗，但未定位到左上角关闭按钮",
                flush=True,
            )
        return True
    except Exception as exc:
        print(f"[{account_id}] [{label}] 地址弹窗处理异常：{_safe_exc(exc)}", flush=True)
        return False


def _confirm_leave_publish_page(page: DpPage) -> None:
    """关闭发布页时如出现离开确认，自动确认。"""
    try:
        page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none' && s.visibility !== 'hidden';
            }
            const keywords = ['确定', '确认', '离开', '放弃', '继续退出'];
            for (const el of document.querySelectorAll('button,a,span,div')) {
                if (!isVisible(el)) continue;
                const text = (el.innerText || el.textContent || '').trim();
                if (keywords.includes(text)) {
                    el.click();
                    return true;
                }
            }
            return false;
            """
        )
        time.sleep(0.5)
    except Exception:
        pass


def _click_submit(page: DpPage, account_id: str, label: str) -> bool:
    print(f"[{account_id}] [{label}] 点击提交并上架...", flush=True)
    try:
        submit_btn = page.ele("text:提交并上架", timeout=3)
        if not submit_btn:
            print(f"[{account_id}] [{label}] 未找到「提交并上架」按钮", flush=True)
            return False
        submit_btn.click(by_js=True)
        time.sleep(2)
        if page.ele("css:.success-title", timeout=8):
            print(f"[{account_id}] [{label}] 成功：多规格商品上架完毕", flush=True)
            return True
        if page.ele("text:请上传预览图", timeout=1):
            print(f"[{account_id}] [{label}] 提交被拦截：仍有预览图未上传", flush=True)
            return False
        print(f"[{account_id}] [{label}] 未检测到成功标志，请手动核查", flush=True)
        return False
    except Exception as exc:
        print(f"[{account_id}] [{label}] 提交异常：{_safe_exc(exc)}", flush=True)
        return False


def upload_one_listing(
    page: DpPage,
    account_id: str,
    unit: ListingUnit,
    product_info: dict[str, Any],
    defaults: dict[str, str],
) -> dict[str, Any]:
    """对单个上架单元执行完整发布流程。"""
    label = unit.listing_label
    covers = [str(p.resolve()) for p in unit.carousel_images]
    details = [str(p.resolve()) for p in unit.detail_images]
    style_names = list(dict.fromkeys(sku.style_name for sku in unit.skus))
    model_names = list(dict.fromkeys(sku.model_name for sku in unit.skus))

    listing_info = dict(product_info)
    listing_info["title"] = resolve_listing_title(product_info, account_id)
    time.sleep(random.uniform(1.0, 2.0))

    print(f"[{account_id}] [{label}] 正在跳转商品分类界面...")
    page.get("https://mms.pinduoduo.com/goods/category")
    time.sleep(5)
    if _dismiss_address_required_page(page, account_id, label):
        _clear_beforeunload(page)
        return _listing_result(unit=unit, status="skipped", reason="address_required")

    ui_type = "A"
    if page.ele("css:.goodsCarousel_btns__22KMn", timeout=1) or page.ele(
        'css:input[data-tracking-click-viewid="local_upload"]', timeout=1
    ):
        ui_type = "C"
    elif page.ele('css:[data-tracking-click-viewid="cate_tree_tab"]', timeout=1):
        ui_type = "B"
    print(f"[{account_id}] [{label}] 路由判定：分支 {ui_type}")

    if ui_type == "C":
        section_ele = page.ele("css:.goodsCarousel_btns__22KMn")
        if section_ele:
            page.run_js('arguments[0].style.display = "flex";', section_ele)
        time.sleep(1)
        cover_input = page.ele('css:input[data-tracking-click-viewid="local_upload"]')
        if cover_input:
            cover_input.input(covers)
        time.sleep(random.uniform(1.5, 2.5))
        listing_info["title"] = apply_title_after_cover_upload(
            page, account_id, product_info, listing_info.get("title", "")
        )
        time.sleep(2)
        next_btn = page.ele("#bottomSubmitBtnId")
        if next_btn:
            next_btn.click()
        time.sleep(5)
        page.wait.load_start()
    else:
        if ui_type == "B":
            tab = page.ele('css:[data-tracking-click-viewid="cate_tree_tab"]')
            if tab:
                page.run_js("arguments[0].click();", tab)
                time.sleep(3)

        search_input = page.ele('css:input[placeholder="请输入关键词搜索分类"]')
        if search_input:
            search_input.click()
            time.sleep(0.5)
            search_input.input(listing_info.get("category_keyword", "玩偶"), clear=True)
        time.sleep(2)
        first_cat = page.ele("css:li.SPP_searchItem_5-188-0")
        if first_cat:
            first_cat.click()
        time.sleep(1)
        confirm = page.ele("text:下一步, 完善商品信息") if ui_type == "B" else page.ele(
            "text:确认发布该类商品"
        )
        if confirm:
            confirm.click()
        time.sleep(5)
        page.wait.load_start()

        section_ele = page.ele("css:.uploadImgEnter.uploadImgEnterNew")
        if section_ele:
            page.run_js('arguments[0].style.display = "flex";', section_ele)
        time.sleep(1)
        cover_input = page.ele(
            'css:input[type="file"]:not([data-tracking-click-viewid="detail_img_localfile_upload"])'
        )
        if cover_input:
            cover_input.input(covers)
        time.sleep(random.uniform(1.5, 2.5))
        listing_info["title"] = apply_title_after_cover_upload(
            page, account_id, product_info, listing_info.get("title", "")
        )
        time.sleep(1)

    print(f"[{account_id}] [{label}] 正在上传详情图...")
    detail_input = page.ele('css:input[data-tracking-click-viewid="detail_img_localfile_upload"]')
    if detail_input and details:
        detail_input.input(details)
    time.sleep(2)

    print(f"[{account_id}] [{label}] 正在录入多规格（款式 + 型号）...")
    add_style_and_model_specs(page, account_id, style_names, model_names)
    time.sleep(1)
    sku_rows = wait_multi_sku_rows(page, account_id, unit.skus)

    print(f"[{account_id}] [{label}] 开始填写价格表...")
    previews_ok = fill_multi_spec_rows(page, account_id, unit.skus, defaults, rows=sku_rows)

    pcode = unit.merchant_code
    global_code = page.ele(
        'xpath://span[contains(text(),"商品编码") or contains(text(),"货号")]/following::input[1]'
    )
    if global_code:
        global_code.input(pcode, clear=True)

    time.sleep(random.uniform(1.0, 2.0))
    if not previews_ok:
        print(f"[{account_id}] [{label}] 预览图未全部就绪，跳过提交", flush=True)
        _clear_beforeunload(page)
        return _listing_result(
            unit=unit,
            status="retryable",
            reason="preview_not_ready",
            retryable=True,
            legacy_status="skipped",
        )

    ok = _click_submit(page, account_id, label)
    _clear_beforeunload(page)
    if ok:
        return _listing_result(
            unit=unit,
            status="success",
            reason="listed",
            title=listing_info.get("title", ""),
            legacy_status="listed",
        )
    return _listing_result(
        unit=unit,
        status="retryable",
        reason="submit_uncertain",
        title=listing_info.get("title", ""),
        retryable=True,
        legacy_status="submit_uncertain",
    )


def run_listing_uploads(
    page: DpPage,
    account_id: str,
    units: list[ListingUnit],
    *,
    category_keyword: str = "玩偶",
    title_mode: str = "page_ai",
    defaults: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """顺序上架多个单元。"""
    product_info = {
        "category_keyword": category_keyword,
        "title_mode": title_mode,
        "title": "",
    }
    defaults = defaults or {}
    results: list[dict[str, Any]] = []

    for idx, unit in enumerate(units):
        if idx > 0:
            print(f"\n[{account_id}] 等待 5 秒后上架下一单元 [{unit.listing_label}]...\n")
            time.sleep(5)
        try:
            results.append(
                upload_one_listing(page, account_id, unit, product_info, defaults)
            )
        except Exception as e:
            err = _safe_exc(e)
            reason, retryable = _classify_exception(e)
            print(f"[{account_id}] [{unit.listing_label}] 业务运行报错: {err}")
            results.append(
                _listing_result(
                    unit=unit,
                    status="retryable" if retryable else "failed",
                    reason=reason,
                    error=err,
                    retryable=retryable,
                    legacy_status="failed",
                )
            )
            if "连接已断开" in err or "disconnect" in err.lower():
                break
            try:
                safe_set = (unit.image_set or "default").replace("/", "_")
                shot = _error_screenshot_path(
                    f"error_listing_{account_id}_{unit.product_code}_{safe_set}.png"
                )
                page.get_screenshot(path=shot)
                print(f"[{account_id}] 已保存报错截图：{shot}", flush=True)
            except Exception:
                pass
    return results
