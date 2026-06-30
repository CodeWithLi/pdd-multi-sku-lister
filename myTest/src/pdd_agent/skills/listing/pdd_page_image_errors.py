"""拼多多页面图片上传报错检测（主图/预览图等共用）。"""

from __future__ import annotations

from typing import Any

PDD_IMAGE_DIMENSION_ERROR_PATTERNS = (
    "尺寸不符合要求",
    "图片尺寸不符合",
    "图片不符合要求",
    "图片尺寸不符",
)


class PddImageDimensionRejected(RuntimeError):
    """拼多多页面拒绝图片上传（如尺寸不合规）。"""

    def __init__(
        self,
        message: str,
        *,
        platform_message: str = "",
        image_kind: str = "",
        sku_label: str = "",
    ):
        super().__init__(message)
        self.platform_message = str(platform_message or message).strip()
        self.image_kind = str(image_kind or "").strip()
        self.sku_label = str(sku_label or "").strip()


# 兼容分支 C 旧名
BranchCCoverImageRejected = PddImageDimensionRejected


def _body_text(page) -> str:
    try:
        text = page.run_js("return document.body?.innerText || '';")
        return str(text or "")
    except Exception:
        return ""


def read_pdd_image_dimension_error(page) -> str:
    """读取页面上「尺寸不符合要求」类 toast/提示。"""
    try:
        msg = page.run_js(
            """
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none' && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            const patterns = [
                '尺寸不符合要求',
                '图片尺寸不符合',
                '图片不符合要求',
                '图片尺寸不符',
            ];
            const selectors = [
                '[class*="toast"]', '[class*="Toast"]',
                '[class*="notice"]', '[class*="Notice"]',
                '[class*="message"]', '[class*="Message"]',
                '[class*="error"]', '[class*="Error"]',
                '[class*="warn"]', '[class*="Warn"]',
                '[class*="tip"]', '[class*="Tip"]',
            ];
            for (const sel of selectors) {
                for (const el of document.querySelectorAll(sel)) {
                    const raw = (el.innerText || el.textContent || '').trim();
                    if (!raw || !isVisible(el)) continue;
                    const compact = raw.replace(/\\s+/g, '');
                    for (const p of patterns) {
                        if (compact.includes(p.replace(/\\s+/g, ''))) return raw;
                    }
                }
            }
            const body = document.body?.innerText || '';
            for (const p of patterns) {
                if (body.includes(p)) return p;
            }
            return '';
            """
        )
        return str(msg or "").strip()
    except Exception:
        body = _body_text(page)
        for pattern in PDD_IMAGE_DIMENSION_ERROR_PATTERNS:
            if pattern in body:
                return pattern
        return ""


def raise_if_pdd_image_dimension_rejected(
    page,
    *,
    account_id: str = "",
    label: str = "",
    image_kind: str = "",
    sku_label: str = "",
) -> None:
    platform_message = read_pdd_image_dimension_error(page)
    if not platform_message:
        return
    prefix = f"[{account_id}] " if account_id else ""
    kind = str(image_kind or "").strip()
    if kind == "preview":
        scope = f"预览图 [{sku_label or label}]" if (sku_label or label) else "预览图"
    elif kind == "carousel":
        scope = "分支 C 主图"
    elif kind == "material":
        scope = "商品素材（白底图）"
    else:
        scope = label or kind or "图片"
    print(
        f"{prefix}{scope}：拼多多图片校验失败：{platform_message}",
        flush=True,
    )
    raise PddImageDimensionRejected(
        f"{prefix}{scope} 上传失败：{platform_message}",
        platform_message=platform_message,
        image_kind=kind,
        sku_label=sku_label or label,
    )
