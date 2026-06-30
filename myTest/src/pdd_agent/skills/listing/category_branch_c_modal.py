"""分支 C「根据图片推荐分类」弹窗：检测与确认（与 upload 主流程隔离）。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage


def _log(account_id: str, label: str, msg: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    if label:
        prefix = f"{prefix} [{label}]" if prefix else f"[{label}]"
    print(f"{prefix} {msg}".strip(), flush=True)


_IMAGE_CATEGORY_RECOMMENDATION_MODAL_JS = """
function isVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 8 && r.height > 8
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function norm(t) {
    return (t || '').replace(/\\s+/g, '');
}
function isCategoryOptionText(t) {
    const s = (t || '').replace(/\\s+/g, ' ').trim();
    if (!s.includes('>')) return false;
    if (s.includes('请选择') || s.includes('根据您上传') || s.includes('为您推荐分类')) return false;
    if (s.includes('确认') && s.includes('取消')) return false;
    const parts = s.split('>').map((x) => x.trim()).filter(Boolean);
    if (parts.length < 2 || parts.length > 4) return false;
    return s.length >= 8 && s.length <= 90;
}
function modalTextMatches(t) {
    if (!t) return false;
    const hasPrompt = t.includes('请选择') || t.includes('为您推荐分类') || t.includes('根据您上传的图片');
    return t.includes('推荐分类') && hasPrompt && (t.includes('确认') || t.includes('取消'));
}
function findModalRoot() {
    const selectors = [
        '[data-testid="beast-core-modal"]',
        '[class*="beast-core-modal"]',
        '[class*="BeastModal"]',
        '[role="dialog"]',
        '[class*="modal"]',
        '[class*="Modal"]',
        '[class*="dialog"]',
        '[class*="Dialog"]',
        '[class*="popup"]',
        '[class*="Popup"]',
    ];
    for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
            if (!isVisible(el)) continue;
            const t = el.innerText || el.textContent || '';
            if (modalTextMatches(t)) return el;
        }
    }
    const bodyText = document.body?.innerText || '';
    if (!modalTextMatches(bodyText)) return null;
    let best = null;
    let bestArea = Number.MAX_SAFE_INTEGER;
    for (const el of document.querySelectorAll('div, section, article, form')) {
        if (!isVisible(el)) continue;
        const t = el.innerText || el.textContent || '';
        if (!modalTextMatches(t)) continue;
        const r = el.getBoundingClientRect();
        const area = r.width * r.height;
        if (area < 12000 || area > window.innerWidth * window.innerHeight * 0.92) continue;
        if (area < bestArea) {
            bestArea = area;
            best = el;
        }
    }
    return best;
}
function detectImageCategoryRecommendationModal() {
    const root = findModalRoot();
    return {
        visible: !!root,
        hasRoot: !!root,
        bodyMatch: modalTextMatches(document.body?.innerText || ''),
    };
}
function isLeafCategoryOption(el) {
    for (const child of el.querySelectorAll('label, li, span, div')) {
        if (child === el) continue;
        const ct = (child.innerText || child.textContent || '').replace(/\\s+/g, ' ').trim();
        if (isCategoryOptionText(ct)) return false;
    }
    return true;
}
function collectModalClickTargets() {
    const root = findModalRoot();
    if (!root) return { ok: false, reason: 'not_visible', targets: [] };
    const targets = [];

    const radios = Array.from(root.querySelectorAll('input[type="radio"]')).filter(isVisible);
    radios.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
    for (const input of radios) {
        const r = input.getBoundingClientRect();
        let labelText = '';
        const label = input.closest('label') || input.parentElement;
        if (label) {
            labelText = (label.innerText || label.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
        }
        targets.push({
            x: r.left + Math.max(4, r.width / 2),
            y: r.top + r.height / 2,
            kind: 'radio',
            t: labelText,
        });
        break;
    }

    if (!targets.length) {
        const options = [];
        for (const el of root.querySelectorAll('[role="radio"], [class*="radio" i], [class*="Radio"], label, li, span, div')) {
            const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
            if (!isCategoryOptionText(t)) continue;
            if (!isVisible(el)) continue;
            if (!isLeafCategoryOption(el)) continue;
            const r = el.getBoundingClientRect();
            options.push({
                x: r.left + Math.min(18, Math.max(8, r.width * 0.08)),
                y: r.top + r.height / 2,
                kind: 'option',
                t,
                area: r.width * r.height,
                yTop: r.top,
            });
        }
        options.sort((a, b) => a.yTop - b.yTop || a.area - b.area || a.t.length - b.t.length);
        if (options.length) {
            const o = options[0];
            targets.push({ x: o.x, y: o.y, kind: 'option', t: o.t });
        }
    }

    for (const el of root.querySelectorAll('button, a, span, div')) {
        const t = norm(el.innerText || el.textContent || '');
        if (t !== '确认') continue;
        if (!isVisible(el)) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 40 || r.height < 24) continue;
        targets.push({
            x: r.left + r.width / 2,
            y: r.top + r.height / 2,
            kind: 'confirm',
            t: '确认',
        });
        break;
    }
    return { ok: targets.length > 0, targets };
}
"""


def body_text_indicates_recommendation_modal(body: str) -> bool:
    text = (body or "").replace("\n", " ")
    if "根据您上传的图片" not in text and "为您推荐分类" not in text:
        return False
    if "推荐分类" not in text:
        return False
    if "请选择" not in text:
        return False
    return "确认" in text or "取消" in text


def _read_body_text(page: DpPage) -> str:
    try:
        return str(page.run_js("return document.body?.innerText || '';") or "")
    except Exception:
        return ""


def _modal_root_visible(page: DpPage) -> bool:
    try:
        raw = page.run_js(
            _IMAGE_CATEGORY_RECOMMENDATION_MODAL_JS
            + "; return detectImageCategoryRecommendationModal();"
        )
        return bool(isinstance(raw, dict) and raw.get("hasRoot"))
    except Exception:
        return False


def log_modal_diagnostics(page: DpPage, account_id: str, label: str) -> dict[str, Any]:
    body = _read_body_text(page)
    info: dict[str, Any] = {"body_match": body_text_indicates_recommendation_modal(body)}
    try:
        raw = page.run_js(
            _IMAGE_CATEGORY_RECOMMENDATION_MODAL_JS
            + "; return detectImageCategoryRecommendationModal();"
        )
        if isinstance(raw, dict):
            info.update(raw)
        targets = page.run_js(
            _IMAGE_CATEGORY_RECOMMENDATION_MODAL_JS + "; return collectModalClickTargets();"
        )
        if isinstance(targets, dict):
            info["target_count"] = len(targets.get("targets") or [])
            info["targets"] = [
                {"kind": t.get("kind"), "t": str(t.get("t") or "")[:60]}
                for t in (targets.get("targets") or [])
                if isinstance(t, dict)
            ]
    except Exception as exc:
        info["js_error"] = str(exc)
    _log(
        account_id,
        label,
        "分支 C 推荐分类弹窗诊断："
        f"visible={bool(info.get('visible'))} hasRoot={bool(info.get('hasRoot'))} "
        f"bodyMatch={bool(info.get('body_match'))} targets={info.get('target_count', 0)} "
        f"{info.get('targets', [])}",
    )
    return info


def is_image_category_recommendation_modal_visible(page: DpPage) -> bool:
    if _modal_root_visible(page):
        return True
    body = _read_body_text(page)
    return body_text_indicates_recommendation_modal(body)


def is_modal_blocking_category_advance(page: DpPage) -> bool:
    return is_image_category_recommendation_modal_visible(page)


def _looks_like_category_option(text: str) -> bool:
    s = (text or "").replace("\n", " ").strip()
    if "请选择" in s or "根据您上传" in s:
        return False
    if ">" not in s:
        return False
    parts = [p.strip() for p in s.split(">") if p.strip()]
    return 2 <= len(parts) <= 4 and len(s) <= 90


def _click_playwright_radio_inputs(page: DpPage) -> str:
    """Playwright 直接点第一个可见 radio。"""
    from pdd_agent.skills.listing import upload as listing_upload

    radios = page.eles('css:input[type="radio"]', timeout=1)
    if radios:
        listing_upload._playwright_mouse_click_element(page, radios[0])
        label_text = (radios[0].text or "").strip()
        if label_text and _looks_like_category_option(label_text):
            return label_text
        return "radio#0"

    for selector in ('css:[role="radio"]', 'css:label:has(input[type="radio"])'):
        elements = page.eles(selector, timeout=0.8)
        for el in elements[:3]:
            text = (el.text or "").strip()
            if text and not _looks_like_category_option(text):
                continue
            if listing_upload._playwright_mouse_click_element(page, el):
                return text or selector
    return ""


def _click_targets_with_mouse(
    page: DpPage,
    account_id: str,
    label: str,
    targets: list[dict[str, Any]],
) -> tuple[str, bool]:
    from pdd_agent.skills.listing import upload as listing_upload

    selected_text = ""
    pick = next((t for t in targets if t.get("kind") in {"radio", "option"}), None)
    confirm = next((t for t in targets if t.get("kind") == "confirm"), None)
    if pick:
        _log(
            account_id,
            label,
            f"分支 C 弹窗：坐标点选 {pick.get('kind')} → {str(pick.get('t') or '')[:60]}",
        )
        if listing_upload._playwright_mouse_at(page, float(pick["x"]), float(pick["y"])):
            selected_text = str(pick.get("t") or "")
            time.sleep(0.5)
    if confirm:
        _log(account_id, label, "分支 C 弹窗：坐标点击「确认」")
        listing_upload._playwright_mouse_at(page, float(confirm["x"]), float(confirm["y"]))
        time.sleep(0.8)
    return selected_text, bool(confirm)


def _attempt_close_recommendation_modal(
    page: DpPage,
    account_id: str,
    label: str,
) -> tuple[bool, str]:
    """点单选框 → 确认；仅弹窗消失才视为成功。"""
    log_modal_diagnostics(page, account_id, label)

    selected_text = _click_playwright_radio_inputs(page)
    if selected_text:
        _log(account_id, label, f"分支 C 弹窗：Playwright 点击 radio → {selected_text[:60]}")
        time.sleep(0.4)
        confirm_el = page.ele("text:确认", timeout=1)
        if confirm_el:
            from pdd_agent.skills.listing import upload as listing_upload

            listing_upload._playwright_mouse_click_element(page, confirm_el)
            time.sleep(0.8)
        if not is_image_category_recommendation_modal_visible(page):
            return True, selected_text

    try:
        raw = page.run_js(
            _IMAGE_CATEGORY_RECOMMENDATION_MODAL_JS + "; return collectModalClickTargets();"
        )
    except Exception:
        raw = None
    info = raw if isinstance(raw, dict) else {}
    targets = [t for t in (info.get("targets") or []) if isinstance(t, dict)]
    if targets:
        selected_text, _ = _click_targets_with_mouse(page, account_id, label, targets)
        if not is_image_category_recommendation_modal_visible(page):
            return True, selected_text

    _log(account_id, label, "分支 C：弹窗仍在（单选框或确认未生效）")
    return False, selected_text


def handle_image_category_recommendation_modal(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    wait_seconds: int = 0,
) -> bool:
    """选第一项 → 点「确认」；无弹窗返回 False；必须弹窗关闭才算成功。"""
    if wait_seconds <= 0:
        if not is_image_category_recommendation_modal_visible(page):
            return False
    else:
        deadline = time.time() + max(0, int(wait_seconds))
        found = False
        while time.time() < deadline:
            if is_image_category_recommendation_modal_visible(page):
                found = True
                break
            time.sleep(0.5)
        if not found:
            return False

    ok, selected_text = _attempt_close_recommendation_modal(page, account_id, label)
    if ok:
        _log(
            account_id,
            label,
            f"分支 C：已关闭「以图推荐分类」弹窗，选中：{selected_text[:80]}",
        )
        return True

    _log(account_id, label, "分支 C：推荐分类弹窗处理失败（未选中或未点确认）")
    log_modal_diagnostics(page, account_id, label)
    return False


def ensure_branch_c_recommendation_modal_cleared(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    wait_seconds: int = 10,
) -> bool:
    """等待并关闭推荐分类弹窗；返回是否已成功关闭。"""
    if wait_seconds > 0:
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if is_image_category_recommendation_modal_visible(page):
                break
            time.sleep(0.5)
        else:
            return False

    if not is_image_category_recommendation_modal_visible(page):
        return False

    for attempt in range(4):
        if not is_image_category_recommendation_modal_visible(page):
            return True
        _log(account_id, label, f"分支 C：处理推荐分类弹窗 ({attempt + 1}/4)")
        ok, _ = _attempt_close_recommendation_modal(page, account_id, label)
        if ok:
            return True
        time.sleep(0.6)

    if is_image_category_recommendation_modal_visible(page):
        _log(account_id, label, "分支 C：推荐分类弹窗多次尝试后仍未关闭")
        return False
    return True
