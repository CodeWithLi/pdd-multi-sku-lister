"""
发布详情页（图一）轮播图补传。

分类页（图二）已上传轮播图后进入详情页，拼多多有时未自动加载。
填标题前先检测「商品轮播图」是否已有图，缺失则补传 1~5 张主图。
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from pdd_agent.skills.listing.pdd_page_image_errors import (
    raise_if_pdd_image_upload_rejected,
)

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

_CAROUSEL_PROGRESS_RE = re.compile(r"已上传\s*(\d+)\s*/\s*(\d+)\s*张")


def parse_detail_page_carousel_progress(text: str) -> tuple[int, int] | None:
    """从页面文本解析「已上传 X/Y 张」。"""
    match = _CAROUSEL_PROGRESS_RE.search(str(text or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def count_detail_page_carousel_images(page: DpPage) -> tuple[int, int]:
    """
    统计图一详情页轮播图数量。

    优先读「已上传 X/Y 张」，否则统计轮播区可见缩略图。
    """
    try:
        result = page.run_js(
            """
            const body = document.body?.innerText || '';
            const m = body.match(/已上传\\s*(\\d+)\\s*\\/\\s*(\\d+)\\s*张/);
            if (m) return [parseInt(m[1], 10), parseInt(m[2], 10)];

            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 30 && r.height > 30
                    && s.display !== 'none' && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }

            let anchor = null;
            for (const el of document.querySelectorAll('div, span, label, p')) {
                const t = (el.innerText || el.textContent || '').trim();
                if (t === '商品轮播图' || t.startsWith('商品轮播图')) {
                    anchor = el;
                    break;
                }
            }

            const roots = [];
            if (anchor) {
                let node = anchor;
                for (let i = 0; i < 8 && node; i++) {
                    roots.push(node);
                    node = node.parentElement;
                }
            }
            roots.push(document.body);

            let visible = 0;
            const seen = new Set();
            for (const root of roots) {
                if (!root) continue;
                for (const img of root.querySelectorAll('img')) {
                    if (seen.has(img)) continue;
                    seen.add(img);
                    const src = (img.getAttribute('src') || '').trim();
                    if (!src || src.startsWith('data:image/svg')) continue;
                    const r = img.getBoundingClientRect();
                    if (!isVisible(img)) continue;
                    if (r.width < 40 || r.height < 40) continue;
                    visible++;
                }
                if (visible > 0) break;
            }
            return [visible, 10];
            """
        )
        if isinstance(result, list) and len(result) >= 2:
            return max(0, int(result[0])), max(1, int(result[1]))
    except Exception:
        pass
    return 0, 10


def is_detail_page_carousel_missing(page: DpPage, *, min_count: int = 1) -> bool:
    uploaded, _total = count_detail_page_carousel_images(page)
    return uploaded < max(1, min_count)


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


def _reveal_detail_page_carousel_section(page: DpPage) -> None:
    for sel in (
        "css:.uploadImgEnter.uploadImgEnterNew",
        "css:[class*='goodsCarousel']",
        "css:[class*='GoodsCarousel']",
        "css:[class*='uploadImg']",
    ):
        section = page.ele(sel, timeout=0.5)
        if not section:
            continue
        try:
            page.run_js(
                """
                arguments[0].style.display = 'flex';
                arguments[0].style.visibility = 'visible';
                arguments[0].style.opacity = '1';
                """,
                section,
            )
        except Exception:
            pass


def _find_detail_page_carousel_input(page: DpPage):
    for sel in (
        'css:input[data-tracking-click-viewid="local_upload"]',
        'css:input[type="file"]:not([data-tracking-click-viewid="detail_img_localfile_upload"])',
        'css:input[type="file"][accept*="image"]',
    ):
        el = page.ele(sel, timeout=0.8)
        if el:
            return el
    return None


def _click_detail_page_carousel_placeholder(page: DpPage) -> bool:
    try:
        clicked = page.run_js(
            """
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none' && s.visibility !== 'hidden';
            }
            for (const el of document.querySelectorAll('div, span, button, label, a')) {
                const t = (el.innerText || el.textContent || '').trim();
                if (!t.includes('上传图片') || !isVisible(el)) continue;
                let p = el;
                for (let i = 0; i < 6 && p; i++) {
                    const pt = (p.innerText || p.textContent || '').trim();
                    if (pt.includes('商品轮播图') || pt.includes('已上传')) {
                        el.click();
                        return true;
                    }
                    p = p.parentElement;
                }
            }
            for (const el of document.querySelectorAll(
                '[class*="carousel"], [class*="Carousel"], [class*="uploadImg"]'
            )) {
                if (!isVisible(el)) continue;
                const t = (el.innerText || el.textContent || '').trim();
                if (t.includes('上传图片') || t.includes('+')) {
                    el.click();
                    return true;
                }
            }
            return false;
            """
        )
        return bool(clicked)
    except Exception:
        return False


def _upload_detail_page_carousel_files(
    page: DpPage,
    cover_input,
    covers: list[str],
    *,
    account_id: str = "",
    label: str = "",
    wait_seconds: int = 18,
) -> bool:
    paths = [str(p) for p in covers if p]
    if not paths:
        _log(account_id, label, "详情页轮播图补传：无可用主图路径")
        return False

    try:
        page.run_js(
            """
            arguments[0].style.display = 'block';
            arguments[0].style.visibility = 'visible';
            arguments[0].style.opacity = '1';
            arguments[0].style.width = '1px';
            arguments[0].style.height = '1px';
            """,
            cover_input,
        )
    except Exception:
        pass

    try:
        cover_input.input(paths if len(paths) > 1 else paths[0])
    except Exception as exc:
        _log(account_id, label, f"详情页轮播图补传：input 上传异常：{exc}")
        return False

    for sec in range(wait_seconds):
        time.sleep(1)
        from pdd_agent.skills.listing.listing_pdd_overlay_dismiss import (
            ensure_image_space_modal_cleared,
        )

        ensure_image_space_modal_cleared(
            page, account_id or "", label or "", max_attempts=1
        )
        raise_if_pdd_image_upload_rejected(
            page,
            account_id=account_id,
            label=label,
            image_kind="carousel",
        )
        current, total = count_detail_page_carousel_images(page)
        if current > 0:
            _log(account_id, label, f"详情页轮播图补传成功：{current}/{total}")
            return True
        if sec in (4, 9, 14):
            _log(
                account_id,
                label,
                f"详情页轮播图补传：等待上传完成… ({sec + 1}/{wait_seconds}s)",
            )

    current, total = count_detail_page_carousel_images(page)
    raise_if_pdd_image_upload_rejected(
        page,
        account_id=account_id,
        label=label,
        image_kind="carousel",
    )
    _log(account_id, label, f"详情页轮播图补传未完成（{current}/{total}）")
    return current > 0


def ensure_detail_page_carousel_before_title(
    page: DpPage,
    covers: list[str],
    *,
    account_id: str = "",
    label: str = "",
    min_count: int = 1,
    max_files: int = 5,
    wait_seconds: int = 18,
) -> bool:
    """
    进入图一详情页、填标题前调用：轮播图缺失则补传 1~max_files 张。

    返回 True 表示页面已有足够轮播图或补传成功；False 表示补传失败。
    """
    uploaded, total = count_detail_page_carousel_images(page)
    if uploaded >= max(1, min_count):
        _log(account_id, label, f"详情页轮播图已存在（{uploaded}/{total}），跳过补传")
        return True

    paths = [str(p) for p in covers if p][: max(1, max_files)]
    if not paths:
        _log(account_id, label, "详情页轮播图缺失，但无本地主图可补传")
        return False

    _log(
        account_id,
        label,
        f"详情页轮播图缺失（{uploaded}/{total}），开始补传 {len(paths)} 张主图…",
    )
    _reveal_detail_page_carousel_section(page)
    time.sleep(0.8)

    for attempt in range(1, 4):
        uploaded, total = count_detail_page_carousel_images(page)
        if uploaded >= max(1, min_count):
            _log(account_id, label, f"详情页轮播图已就绪（{uploaded}/{total}）")
            return True

        cover_input = _find_detail_page_carousel_input(page)
        if not cover_input:
            _click_detail_page_carousel_placeholder(page)
            time.sleep(0.6)
            cover_input = _find_detail_page_carousel_input(page)
        if not cover_input:
            _log(account_id, label, f"详情页轮播图补传：第 {attempt}/3 次未找到 file input")
            time.sleep(1.0)
            continue

        if _upload_detail_page_carousel_files(
            page,
            cover_input,
            paths,
            account_id=account_id,
            label=label,
            wait_seconds=wait_seconds,
        ):
            return True

        _click_detail_page_carousel_placeholder(page)
        time.sleep(0.8)

    uploaded, total = count_detail_page_carousel_images(page)
    ok = uploaded >= max(1, min_count)
    if not ok:
        _log(account_id, label, f"详情页轮播图补传失败，仍为 {uploaded}/{total}")
    return ok
