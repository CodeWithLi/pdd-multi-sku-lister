"""上架标题策略（page_ai / custom）。"""

from __future__ import annotations


def resolve_listing_title(product_info: dict, account_id: str = "", log=print) -> str:
    mode = (product_info.get("title_mode") or "page_ai").strip().lower()
    prefix = f"[{account_id}] " if account_id else ""

    if mode in ("page_ai", "页面ai", "页面ai生成"):
        log(f"{prefix}标题模式：页面 AI 推荐（上传主图后点击「立即使用」）")
        return ""

    title = (product_info.get("title") or "").strip()
    if not title:
        title = f"{product_info.get('category_keyword', '商品')}"
    log(f"{prefix}标题模式：自定义 → {title}")
    return title
