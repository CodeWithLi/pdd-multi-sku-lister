"""分类页点「下一步」未跳转：生成具体中文失败原因。"""

from __future__ import annotations

import re
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.domain.listing_errors import ListingErrors


def _extract_selected_category_path(body: str) -> str:
    text = str(body or "").replace("\n", " ")
    for pattern in (
        r"已选分类[:：]?\s*([^>\n]{2,40}(?:>\s*[^>\n]{2,40}){2,5})",
        r"已根据主轮播图选择分类[:：]?\s*([^>\n]{2,40}(?:>\s*[^>\n]{2,40}){2,5})",
    ):
        matched = re.search(pattern, text)
        if matched:
            return matched.group(1).strip()
    return ""


def collect_category_next_step_issues(
    page: DpPage,
    *,
    ui_type: str = "C",
    listing_info: dict[str, Any] | None = None,
    category_mode: str = "",
) -> list[str]:
    """收集分类页未能进入详情页的具体原因。"""
    from pdd_agent.skills.listing import upload as listing_upload
    from pdd_agent.skills.listing.category_branch_c_modal import (
        is_modal_blocking_category_advance,
    )
    from pdd_agent.skills.listing.category_branch_c_recent import (
        read_branch_c_category_selection_state,
    )

    issues: list[str] = []
    seen: set[str] = set()
    info = dict(listing_info or {})
    branch = str(ui_type or "C").strip().upper() or "C"
    mode = str(category_mode or "").strip()

    def _add(line: str) -> None:
        text = str(line or "").strip()
        if text and text not in seen:
            seen.add(text)
            issues.append(text)

    body = listing_upload._category_page_body_text(page)
    submit_state = listing_upload._read_category_submit_state(page)
    sel_state = read_branch_c_category_selection_state(page)
    selected_path = _extract_selected_category_path(body)

    modal_open = (
        is_modal_blocking_category_advance(page)
        or listing_upload._is_image_category_recommendation_modal_visible(page)
    )
    if modal_open:
        _add("「根据图片推荐分类」弹窗未确认，挡住了下一步")

    blocking = bool(
        submit_state.get("blocking")
        or sel_state.get("blocking")
        or "请选择完整的分类" in body
        or "请选择完整分类" in body
    )
    if blocking:
        _add("商品类目未选完整（页面提示：请选择完整的分类）")
    elif branch == "C" and not sel_state.get("pathReady"):
        if not listing_upload._branch_c_category_already_selected(page):
            if listing_upload._category_page_needs_manual_selection(page):
                if "暂无推荐" in body:
                    _add("平台暂无推荐分类，需手动选类但未选定完整路径")
                elif "选择分类" in body:
                    _add("需点击「选择分类」手动选定三级类目，当前未完成")
                else:
                    _add("需手动选择商品类目，当前未选定完整路径")
            elif sel_state.get("recentPaths") and not sel_state.get("autoSelected"):
                _add("有「最近使用」类目可选，但未选中完整分类路径")
            else:
                _add("商品类目路径未就绪，分类区块可能仍在渲染")

    if not submit_state.get("visible"):
        _add("页面上未显示「下一步，完善商品信息」按钮")
    elif submit_state.get("disabled"):
        _add("「下一步」按钮仍为禁用状态（类目或页面校验未通过）")

    if submit_state.get("manualPickerOpen"):
        _add("分类选择弹层仍打开，页面校验未收起")

    carousel_current, carousel_total = listing_upload._branch_c_carousel_upload_count(page)
    if carousel_current < 1:
        _add(f"主图/轮播图未上传（当前 {carousel_current}/{carousel_total} 张）")

    title = str(info.get("title") or "").strip()
    title_mode = str(info.get("title_mode") or "").strip().lower()
    if title_mode in {"page_ai", "ai"} and not title and branch == "C":
        _add("AI 标题页未填入商品标题，可能导致无法点下一步")

    if branch == "C" and "商品分类" in body and not sel_state.get("onPage"):
        if "商品分类渲染等待超时" in body or not issues:
            _add("商品分类区域未加载完成或渲染超时")

    if selected_path and blocking:
        _add(f"当前已选类目：{selected_path[:80]}（路径不完整或未确认）")
    elif selected_path and not sel_state.get("pathReady"):
        _add(f"当前类目显示为：{selected_path[:80]}（平台未认可为完整路径）")

    if mode == "manual_picker" and not sel_state.get("pathReady"):
        _add("手动选类模式下，三级类目仍未确认完成")

    if branch != "C" and not blocking and not submit_state.get("visible"):
        keyword = str(info.get("category_keyword") or info.get("category") or "").strip()
        if keyword:
            _add(f"分类搜索「{keyword}」后未出现可点的下一步")

    if not issues:
        if listing_upload._is_still_on_category_publish_step(page):
            _add("已点击「下一步」，但页面仍停留在分类页，未能进入商品详情")
        else:
            _add("分类流程未完成，未能进入商品详情填写页")

    return issues


def build_category_next_step_failure_detail(
    page: DpPage,
    *,
    merchant_code: str = "",
    ui_type: str = "C",
    listing_info: dict[str, Any] | None = None,
    category_mode: str = "",
) -> str:
    """拼成飞书一行具体说明。"""
    issues = collect_category_next_step_issues(
        page,
        ui_type=ui_type,
        listing_info=listing_info,
        category_mode=category_mode,
    )
    return ListingErrors.format_validation_detail_brief(issues, merchant_code=merchant_code)


def build_category_next_step_not_found_detail(
    page: DpPage,
    *,
    merchant_code: str = "",
    ui_type: str = "C",
    listing_info: dict[str, Any] | None = None,
) -> str:
    """未找到下一步按钮时的具体说明。"""
    from pdd_agent.skills.listing import upload as listing_upload

    issues: list[str] = ["未找到「下一步，完善商品信息」按钮"]
    submit_state = listing_upload._read_category_submit_state(page)
    if not submit_state.get("visible"):
        issues.append("页面当前未渲染出底部提交按钮")
    body = listing_upload._category_page_body_text(page)
    if "商品分类" not in body and "下一步" not in body:
        issues.append("可能未进入商品发布分类页（页面结构异常）")
    return ListingErrors.format_validation_detail_brief(
        issues,
        merchant_code=merchant_code,
    )
