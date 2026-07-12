"""发布页商品类目：等待推荐出现后选择第一条。"""

from __future__ import annotations

import time

from playwright.sync_api import Page

from dy_agent.skills.listing.category_page_flow import resolve_category_render_wait


def _log(account_id: str, label: str, message: str) -> None:
    print(f"[{account_id}] [{label}] {message}", flush=True)


def _read_selected_category(page: Page) -> str:
    try:
        return str(
            page.evaluate(
                """
                () => {
                  const nodes = Array.from(document.querySelectorAll('*'));
                  for (const el of nodes) {
                    const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (!t || !t.includes('>')) continue;
                    if (t.includes('商品类目') || t.includes('更多推荐') || t.includes('更多类目')) continue;
                    if (t.length < 6 || t.length > 120) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 20 || r.height < 10) continue;
                    return t;
                  }
                  return '';
                }
                """
            )
        ).strip()
    except Exception:
        return ""


def _click_first_recommended_category(page: Page) -> bool:
    return bool(
        page.evaluate(
            """
            () => {
              function visible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 20 && r.height > 10 && s.display !== 'none' && s.visibility !== 'hidden';
              }
              const skip = new Set(['更多推荐', '更多类目', '商品类目']);
              const items = [];
              for (const el of document.querySelectorAll('div, span, a, li, button')) {
                const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                if (!t || !t.includes('>')) continue;
                if (skip.has(t)) continue;
                if (t.length < 6 || t.length > 120) continue;
                if (!visible(el)) continue;
                const r = el.getBoundingClientRect();
                items.push({ el, top: r.top, left: r.left, text: t });
              }
              items.sort((a, b) => a.top - b.top || a.left - b.left);
              if (!items.length) return false;
              items[0].el.click();
              return items[0].text;
            }
            """
        )
    )


def wait_and_select_first_category(
    page: Page,
    account_id: str,
    label: str,
    *,
    burst_demo: bool = True,
    max_wait: int | None = None,
) -> str:
    """等待类目区块渲染后点击第一个推荐类目。"""
    wait_budget = max_wait or resolve_category_render_wait(burst_demo=burst_demo)
    if burst_demo:
        _log(account_id, label, f"等待商品类目渲染（最多 {wait_budget}s，burst_demo）")
    else:
        _log(account_id, label, f"等待商品类目渲染（最多 {wait_budget}s）")

    selected = ""
    for sec in range(wait_budget):
        selected = _read_selected_category(page)
        if selected and ">" in selected:
            _log(account_id, label, f"商品类目已出现：{selected}")
            return selected

        body = ""
        try:
            body = page.locator("body").inner_text(timeout=1_000)
        except Exception:
            pass
        if "商品类目" in body:
            clicked = _click_first_recommended_category(page)
            if clicked:
                if isinstance(clicked, str):
                    selected = clicked
                else:
                    time.sleep(1)
                    selected = _read_selected_category(page)
                if selected:
                    _log(account_id, label, f"已选择推荐类目：{selected}")
                    return selected

        if sec == 0 or (sec + 1) % 5 == 0:
            _log(account_id, label, f"等待商品类目… ({sec + 1}/{wait_budget}s)")
        time.sleep(1)

    selected = _read_selected_category(page)
    if selected:
        return selected
    raise RuntimeError(f"[{account_id}] [{label}] 超时未出现可选择的商品类目")
