"""抖店发布页 AI 标题：等待推荐栏「立即使用」，否则点 AI 生成。"""

from __future__ import annotations

import time

from playwright.sync_api import Page

TITLE_MODE_PAGE_AI = "page_ai"
# 抖店与拼多多不同：先等 15s 再轮询
DEFAULT_INITIAL_WAIT = 15
DEFAULT_MAX_WAIT = 30


def _log(account_id: str, label: str, message: str) -> None:
    print(f"[{account_id}] [{label}] {message}", flush=True)


def _read_title_from_input(page: Page) -> str:
    selectors = [
        'input[placeholder*="商品标题"]',
        'input[placeholder*="标题"]',
        'textarea[placeholder*="商品标题"]',
        'textarea[placeholder*="标题"]',
        'input[maxlength="60"]',
        'textarea[maxlength="60"]',
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        if locator.count() == 0:
            continue
        for reader in ("input_value", "get_attribute"):
            try:
                if reader == "input_value":
                    value = str(locator.input_value(timeout=1_000)).strip()
                else:
                    value = str(locator.get_attribute("value") or "").strip()
                if value:
                    return value
            except Exception:
                continue

    try:
        title = str(
            page.evaluate(
                """
                () => {
                  function visible(el) {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 30 && r.height > 8
                      && s.display !== 'none' && s.visibility !== 'hidden';
                  }
                  function readValue(el) {
                    if (!el) return '';
                    return String(el.value ?? el.innerText ?? el.textContent ?? '').trim();
                  }
                  function looksLikeTitle(val) {
                    return val.length >= 4 && val.length <= 60 && !/^[0-9/\\s]+$/.test(val);
                  }

                  for (const el of document.querySelectorAll('label, span, div, p')) {
                    const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (!t.includes('商品标题')) continue;
                    let root = el;
                    for (let i = 0; i < 10 && root; i++) {
                      for (const inp of root.querySelectorAll(
                        'input, textarea, [contenteditable="true"]'
                      )) {
                        if (!visible(inp)) continue;
                        const val = readValue(inp);
                        if (looksLikeTitle(val)) return val;
                      }
                      root = root.parentElement;
                    }
                  }

                  for (const inp of document.querySelectorAll(
                    'input[maxlength="60"], textarea[maxlength="60"]'
                  )) {
                    if (!visible(inp)) continue;
                    const val = readValue(inp);
                    if (looksLikeTitle(val)) return val;
                  }

                  for (const inp of document.querySelectorAll('input, textarea')) {
                    const ph = inp.getAttribute('placeholder') || '';
                    if (!ph.includes('标题')) continue;
                    if (!visible(inp)) continue;
                    const val = readValue(inp);
                    if (looksLikeTitle(val)) return val;
                  }
                  return '';
                }
                """
            )
        ).strip()
        if title:
            return title
    except Exception:
        pass

    return ""


def _click_use_now(page: Page) -> bool:
    if page.get_by_text("立即使用", exact=True).count() > 0:
        try:
            page.get_by_text("立即使用", exact=True).first.click(timeout=2_000)
            return True
        except Exception:
            pass

    return bool(
        page.evaluate(
            """
            () => {
              function visible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 2 && r.height > 2 && s.display !== 'none' && s.visibility !== 'hidden';
              }
              for (const el of document.querySelectorAll('a, span, button, div')) {
                const t = (el.innerText || el.textContent || '').trim();
                if (t !== '立即使用' || !visible(el)) continue;
                let p = el;
                for (let i = 0; i < 10 && p; i++) {
                  const pt = p.innerText || '';
                  if (pt.includes('AI标题推荐') || pt.includes('AI 标题推荐') || pt.includes('标题推荐')) {
                    el.click();
                    return true;
                  }
                  p = p.parentElement;
                }
              }
              for (const el of document.querySelectorAll('a, span, button')) {
                const t = (el.innerText || el.textContent || '').trim();
                if (t === '立即使用' && visible(el)) {
                  el.click();
                  return true;
                }
              }
              return false;
            }
            """
        )
    )


def _click_ai_generate_button(page: Page) -> bool:
    candidates = [
        page.locator('button:has-text("AI")'),
        page.locator('[class*="ai"]').filter(has_text="AI"),
        page.get_by_text("AI生成", exact=False),
        page.get_by_text("AI生成标题", exact=False),
    ]
    for locator in candidates:
        if locator.count() == 0:
            continue
        try:
            locator.first.click(timeout=2_000)
            return True
        except Exception:
            continue

    return bool(
        page.evaluate(
            """
            () => {
              const input = document.querySelector('input[placeholder*="标题"], textarea[placeholder*="标题"]');
              const ir = input ? input.getBoundingClientRect() : null;
              for (const el of document.querySelectorAll('button, span, div')) {
                const t = (el.innerText || el.textContent || '').trim();
                if (!['AI', 'AI生成', 'AI生成标题'].includes(t)) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) continue;
                if (ir && Math.abs(r.top - ir.top) > 80) continue;
                el.click();
                return true;
              }
              return false;
            }
            """
        )
    )


def wait_and_apply_page_ai_title(
    page: Page,
    account_id: str,
    label: str,
    *,
    title_mode: str = TITLE_MODE_PAGE_AI,
    initial_wait: int = DEFAULT_INITIAL_WAIT,
    max_wait: int = DEFAULT_MAX_WAIT,
) -> str:
    """上传主图后填充 AI 标题。抖店默认先等 15s。"""
    mode = (title_mode or "").strip().lower()
    if mode not in (TITLE_MODE_PAGE_AI, "page_ai", "页面ai"):
        _log(account_id, label, f"标题模式={title_mode}，跳过页面 AI 标题")
        return _read_title_from_input(page)

    title = _read_title_from_input(page)
    if title:
        _log(account_id, label, f"标题已就绪（主图后自动填充，跳过 AI 等待）：{title}")
        return title

    _log(account_id, label, f"标题模式：页面 AI（先等待 {initial_wait}s）")
    time.sleep(initial_wait)

    ai_generate_tried = False
    for sec in range(max_wait):
        title = _read_title_from_input(page)
        if title:
            _log(account_id, label, f"标题已就绪：{title}")
            return title

        body = ""
        try:
            body = page.locator("body").inner_text(timeout=1_000)
        except Exception:
            pass

        if "立即使用" in body or "AI标题推荐" in body or "AI 标题推荐" in body:
            if _click_use_now(page):
                time.sleep(1.5)
                title = _read_title_from_input(page)
                if title:
                    _log(account_id, label, f"已点击「立即使用」，标题：{title}")
                    return title

        if not ai_generate_tried and sec >= 3:
            ai_generate_tried = True
            _log(account_id, label, "未出现「立即使用」，尝试点击 AI 生成标题…")
            if _click_ai_generate_button(page):
                time.sleep(2)
                title = _read_title_from_input(page)
                if title:
                    _log(account_id, label, f"AI 生成标题成功：{title}")
                    return title

        if sec == 0 or (sec + 1) % 5 == 0:
            _log(
                account_id,
                label,
                f"等待 AI 标题推荐… ({sec + 1 + initial_wait}/{initial_wait + max_wait}s)",
            )
        time.sleep(1)

    if _click_ai_generate_button(page):
        time.sleep(2)
        title = _read_title_from_input(page)
        if title:
            return title

    title = _read_title_from_input(page)
    if title:
        _log(account_id, label, f"超时轮询结束但标题已存在，继续：{title}")
        return title

    raise RuntimeError(f"[{account_id}] [{label}] 超时未获取 AI 标题")
