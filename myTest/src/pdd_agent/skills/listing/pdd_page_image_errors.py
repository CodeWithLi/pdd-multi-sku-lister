"""拼多多页面图片上传报错检测（主图/预览图等共用）。"""

from __future__ import annotations

PDD_IMAGE_DIMENSION_ERROR_PATTERNS = (
    "尺寸不符合要求",
    "图片尺寸不符合",
    "图片不符合要求",
    "图片尺寸不符",
)

PDD_IMAGE_FILE_SIZE_ERROR_PATTERNS = (
    "上传图片大小不能超过",
    "图片大小不能超过",
    "大小不能超过3MB",
    "大小不能超过3M",
    "不能超过3MB",
    "不能超过3M",
    "文件大小不能超过",
    "图片过大",
)


class PddImageUploadRejected(RuntimeError):
    """拼多多页面拒绝图片上传（尺寸/文件大小等）。"""

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


class PddImageDimensionRejected(PddImageUploadRejected):
    """拼多多页面拒绝图片上传（像素尺寸不合规）。"""


class PddImageFileSizeRejected(PddImageUploadRejected):
    """拼多多页面拒绝图片上传（文件大小超限，如 >3MB）。"""


# 兼容分支 C 旧名
BranchCCoverImageRejected = PddImageUploadRejected


def _body_text(page) -> str:
    try:
        text = page.run_js("return document.body?.innerText || '';")
        return str(text or "")
    except Exception:
        return ""


def _read_pdd_image_error(page, patterns: tuple[str, ...]) -> str:
    if not patterns:
        return ""
    try:
        patterns_js = ",\n                ".join(repr(p) for p in patterns)
        msg = page.run_js(
            f"""
            function isVisible(el) {{
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none' && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }}
            const patterns = [
                {patterns_js}
            ];
            const selectors = [
                '[class*="toast"]', '[class*="Toast"]',
                '[class*="notice"]', '[class*="Notice"]',
                '[class*="message"]', '[class*="Message"]',
                '[class*="error"]', '[class*="Error"]',
                '[class*="warn"]', '[class*="Warn"]',
                '[class*="tip"]', '[class*="Tip"]',
            ];
            for (const sel of selectors) {{
                for (const el of document.querySelectorAll(sel)) {{
                    const raw = (el.innerText || el.textContent || '').trim();
                    if (!raw || !isVisible(el)) continue;
                    const compact = raw.replace(/\\s+/g, '');
                    for (const p of patterns) {{
                        if (compact.includes(p.replace(/\\s+/g, ''))) return raw;
                    }}
                }}
            }}
            const body = document.body?.innerText || '';
            for (const p of patterns) {{
                if (body.includes(p)) return p;
            }}
            return '';
            """
        )
        return str(msg or "").strip()
    except Exception:
        body = _body_text(page)
        for pattern in patterns:
            if pattern in body:
                return pattern
        return ""


def read_pdd_image_dimension_error(page) -> str:
    """读取页面上「尺寸不符合要求」类 toast/提示。"""
    return _read_pdd_image_error(page, PDD_IMAGE_DIMENSION_ERROR_PATTERNS)


def read_pdd_image_file_size_error(page) -> str:
    """读取页面上「图片大小不能超过 3MB」类 toast/提示。"""
    return _read_pdd_image_error(page, PDD_IMAGE_FILE_SIZE_ERROR_PATTERNS)


def _scope_for_image_kind(
    *,
    image_kind: str = "",
    label: str = "",
    sku_label: str = "",
) -> str:
    kind = str(image_kind or "").strip()
    if kind == "preview":
        return f"预览图 [{sku_label or label}]" if (sku_label or label) else "预览图"
    if kind == "carousel":
        return "分支 C 主图"
    if kind == "material":
        return "商品素材（白底图）"
    return label or kind or "图片"


def _raise_pdd_image_rejected(
    page,
    *,
    account_id: str = "",
    label: str = "",
    image_kind: str = "",
    sku_label: str = "",
    platform_message: str,
    exc_cls: type[PddImageUploadRejected],
) -> None:
    prefix = f"[{account_id}] " if account_id else ""
    scope = _scope_for_image_kind(
        image_kind=image_kind,
        label=label,
        sku_label=sku_label,
    )
    print(
        f"{prefix}{scope}：拼多多图片校验失败：{platform_message}",
        flush=True,
    )
    raise exc_cls(
        f"{prefix}{scope} 上传失败：{platform_message}",
        platform_message=platform_message,
        image_kind=image_kind,
        sku_label=sku_label or label,
    )


def raise_if_pdd_image_upload_rejected(
    page,
    *,
    account_id: str = "",
    label: str = "",
    image_kind: str = "",
    sku_label: str = "",
) -> None:
    """检测拼多多页面图片上传报错（先文件大小，再像素尺寸）。"""
    platform_message = read_pdd_image_file_size_error(page)
    if platform_message:
        _raise_pdd_image_rejected(
            page,
            account_id=account_id,
            label=label,
            image_kind=image_kind,
            sku_label=sku_label,
            platform_message=platform_message,
            exc_cls=PddImageFileSizeRejected,
        )
        return

    platform_message = read_pdd_image_dimension_error(page)
    if not platform_message:
        return
    _raise_pdd_image_rejected(
        page,
        account_id=account_id,
        label=label,
        image_kind=image_kind,
        sku_label=sku_label,
        platform_message=platform_message,
        exc_cls=PddImageDimensionRejected,
    )


def raise_if_pdd_image_dimension_rejected(
    page,
    *,
    account_id: str = "",
    label: str = "",
    image_kind: str = "",
    sku_label: str = "",
) -> None:
    """兼容旧调用：同时检测文件大小与像素尺寸报错。"""
    raise_if_pdd_image_upload_rejected(
        page,
        account_id=account_id,
        label=label,
        image_kind=image_kind,
        sku_label=sku_label,
    )
