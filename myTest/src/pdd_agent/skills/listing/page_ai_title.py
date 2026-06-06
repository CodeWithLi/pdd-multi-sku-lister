"""
拼多多发布页「AI 智能推荐标题」→ 点击「立即使用」填充标题。
"""
from __future__ import annotations

import time

TITLE_MODE_PAGE_AI = "page_ai"
DEFAULT_INITIAL_WAIT = 5
DEFAULT_MAX_WAIT = 30


def is_page_ai_title_mode(product_info: dict) -> bool:
    mode = (product_info.get("title_mode") or "").strip().lower()
    return mode in (TITLE_MODE_PAGE_AI, "page_ai", "页面ai", "页面ai生成")


def _log(account_id: str, msg: str):
    prefix = f"[{account_id}] " if account_id else ""
    print(f"{prefix}{msg}")


def _read_title_from_input(page) -> str:
    selectors = (
        'css:input[placeholder^="商品标题组成"]',
        'css:.IPT_inputBlockCell_5-188-0 input',
        'xpath://*[contains(text(),"商品标题")]/following::input[1]',
        'xpath://input[contains(@placeholder,"标题")]',
    )
    for sel in selectors:
        inp = page.ele(sel, timeout=1)
        if not inp:
            continue
        val = (inp.attr("value") or inp.value or "").strip()
        if val:
            return val
    return ""


def _find_use_now_button(page):
    """查找「立即使用」链接/按钮（需在 AI 推荐栏附近）。"""
    candidates = (
        page.ele('text:立即使用', timeout=0.5),
        page.ele('xpath://*[contains(text(),"AI智能推荐标题")]/following::*[normalize-space(text())="立即使用"][1]', timeout=0.5),
        page.ele('xpath://*[contains(text(),"AI智能推荐") and contains(text(),"立即使用")]//*[normalize-space(text())="立即使用"]', timeout=0.5),
        page.ele('xpath://a[normalize-space(text())="立即使用"]', timeout=0.5),
        page.ele('xpath://span[normalize-space(text())="立即使用"]', timeout=0.5),
    )
    for ele in candidates:
        if ele:
            return ele
    return None


def _click_use_now_via_js(page) -> bool:
    return bool(
        page.run_js(
            """
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none' && s.visibility !== 'hidden';
            }
            const bodyText = document.body.innerText || '';
            if (!bodyText.includes('AI智能推荐') && !bodyText.includes('立即使用')) {
                return false;
            }
            const nodes = document.querySelectorAll('a, span, button, div');
            for (const n of nodes) {
                const t = (n.innerText || n.textContent || '').trim();
                if (t !== '立即使用' || !isVisible(n)) continue;
                let p = n.parentElement;
                for (let i = 0; i < 8 && p; i++) {
                    const pt = p.innerText || '';
                    if (pt.includes('AI智能推荐标题') || pt.includes('AI智能推荐')) {
                        n.click();
                        return true;
                    }
                    p = p.parentElement;
                }
            }
            for (const n of nodes) {
                const t = (n.innerText || n.textContent || '').trim();
                if (t === '立即使用' && isVisible(n)) {
                    n.click();
                    return true;
                }
            }
            return false;
            """
        )
    )


def wait_and_apply_page_ai_title(
    page,
    account_id: str = "",
    initial_wait: int = DEFAULT_INITIAL_WAIT,
    max_wait: int = DEFAULT_MAX_WAIT,
) -> str:
    """
    上传主图后等待拼多多页面出现 AI 推荐栏，点击「立即使用」填充标题。
    返回填入的标题文本。
    """
    _log(account_id, "标题模式：页面 AI 推荐（上传图片后等待「立即使用」）")
    time.sleep(initial_wait)

    for sec in range(max_wait):
        bar = page.ele("text:AI智能推荐标题", timeout=0.5)
        use_btn = _find_use_now_button(page)

        if use_btn or bar:
            if not use_btn:
                use_btn = _find_use_now_button(page)
            if not use_btn and _click_use_now_via_js(page):
                time.sleep(1.5)
                title = _read_title_from_input(page)
                if title:
                    _log(account_id, f"已通过 JS 点击「立即使用」，标题：{title}")
                    return title
            elif use_btn:
                try:
                    page.run_js('arguments[0].scrollIntoView({block:"center"});', use_btn)
                    use_btn.click()
                except Exception:
                    _click_use_now_via_js(page)
                time.sleep(1.5)
                title = _read_title_from_input(page)
                if title:
                    _log(account_id, f"已点击「立即使用」，标题：{title}")
                    return title
                time.sleep(2)
                title = _read_title_from_input(page)
                if title:
                    _log(account_id, f"已点击「立即使用」，标题：{title}")
                    return title
                _log(account_id, "已点击「立即使用」，但标题输入框仍为空，继续等待…")

        if sec == 0 or (sec + 1) % 5 == 0:
            _log(account_id, f"等待 AI 推荐标题栏出现… ({sec + 1 + initial_wait}/{initial_wait + max_wait}s)")
        time.sleep(1)

    raise RuntimeError(
        f"[{account_id}] 超时未出现可点击的「立即使用」，页面 AI 标题填充失败"
        if account_id
        else "超时未出现可点击的「立即使用」，页面 AI 标题填充失败"
    )


def _fill_manual_title(page, account_id: str, title: str) -> bool:
    if not title:
        return False

    filled = False
    title_input = page.ele('css:input[placeholder^="商品标题组成"]', timeout=2)
    if title_input:
        title_input.input(title, clear=True)
        page.run_js("arguments[0].blur();", title_input)
        filled = True

    title_wrapper = page.ele("css:.IPT_inputBlockCell_5-188-0", timeout=1)
    if title_wrapper:
        inp = title_wrapper.ele("tag:input", timeout=1)
        if inp:
            inp.input(title, clear=True)
            page.run_js("arguments[0].blur();", inp)
            filled = True

    if filled:
        _log(account_id, f"已填入标题：{title}")
    return filled


def apply_title_after_cover_upload(
    page,
    account_id: str,
    product_info: dict,
    resolved_title: str = "",
    initial_wait: int = DEFAULT_INITIAL_WAIT,
    max_wait: int = DEFAULT_MAX_WAIT,
) -> str:
    """
    主图上传完成后填写标题：
    - page_ai：等待并点击「立即使用」
    - 其它模式：填入 resolved_title
    """
    if is_page_ai_title_mode(product_info):
        return wait_and_apply_page_ai_title(
            page, account_id, initial_wait=initial_wait, max_wait=max_wait
        )

    if not (resolved_title or "").strip():
        raise ValueError(f"[{account_id}] 标题为空，无法填入")
    if not _fill_manual_title(page, account_id, resolved_title.strip()):
        raise RuntimeError(f"[{account_id}] 未找到商品标题输入框")
    return resolved_title.strip()
