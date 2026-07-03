"""规格校验填表失败说明：生成飞书失败表可用的中文短句。"""

from __future__ import annotations

from typing import Any

_ISSUE_REASON_CN: dict[str, str] = {
    "slot_catalog_mismatch": "槽位与商品表尺寸不一致",
    "forward_verify_failed": "填写后编码或价格校验未通过",
    "fill_failed": "格位填写失败",
    "duplicate_spec_pair": "重复「款式+尺寸」映射",
    "spec_code_not_on_page": "页面未找到规格编码行",
    "reverse_style_mismatch": "按编码反查款式不一致",
    "reverse_size_mismatch": "按编码反查尺寸不一致",
    "preview_missing_after_verify": "校验通过后预览图缺失",
    "verify_failed": "回读校验未通过",
}


def _issue_identity(item: dict[str, Any]) -> str:
    combo = str(item.get("combo_folder") or "").strip()
    if combo:
        return combo
    style = str(item.get("style") or "").strip()
    size = str(item.get("size") or "").strip()
    if style and size:
        return f"{style}/{size}"
    return style or size or ""


def describe_spec_fill_issue(item: dict[str, Any]) -> str:
    """单条规格填表/校验问题 → 一行中文。"""
    reason = str(item.get("reason") or "").strip()
    identity = _issue_identity(item)
    detail = str(item.get("detail") or "").strip()
    catalog = str(item.get("catalog_size") or "").strip()
    slot = str(item.get("slot_size") or "").strip()

    if catalog and slot:
        if identity:
            return f"{identity} 商品表「{catalog}」≠页面槽位「{slot}」"
        return f"商品表「{catalog}」≠页面槽位「{slot}」"

    if reason == "slot_catalog_mismatch":
        if identity:
            return f"{identity} 槽位与商品表尺寸不一致"
        return "槽位与商品表尺寸不一致"

    if reason == "duplicate_spec_pair":
        style = str(item.get("style") or "").strip()
        size = str(item.get("size") or "").strip()
        if style and size:
            return f"重复规格 {style}/{size}" + (f"（{identity}）" if identity else "")

    if reason == "forward_verify_failed":
        if identity:
            return f"{identity} 填写后编码或价格与预期不符"
        return "填写后编码或价格与预期不符"

    if reason == "spec_code_not_on_page":
        return f"{identity or '规格编码'} 在页面未找到对应行（可能虚拟滚动未加载）"

    if reason == "reverse_style_mismatch":
        return detail or (f"{identity} 按编码反查款式与预期不一致" if identity else "按编码反查款式不一致")

    if reason == "reverse_size_mismatch":
        return detail or (f"{identity} 按编码反查尺寸与预期不一致" if identity else "按编码反查尺寸不一致")

    if reason.startswith("fill_retry") or reason == "fill_failed":
        label = _ISSUE_REASON_CN.get("fill_failed", "格位填写失败")
        return f"{identity} {label}" if identity else label

    if reason == "preview_missing_after_verify":
        return f"{identity or '规格'} 预览图未上传" if identity else "预览图未上传"

    if detail:
        return f"{identity} {detail}" if identity else detail

    label = _ISSUE_REASON_CN.get(reason, "")
    if label and identity:
        return f"{identity} {label}"
    if label:
        return label
    if identity:
        return identity
    return reason or "规格填表异常"


def _collect_issue_lines(fill_stats: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for key in (
        "slot_catalog_mismatches",
        "failed_items",
        "verify_issues",
        "duplicate_spec_pairs",
    ):
        for raw in fill_stats.get(key) or []:
            if not isinstance(raw, dict):
                continue
            line = describe_spec_fill_issue(raw).strip()
            if line and line not in seen:
                seen.add(line)
                lines.append(line)
    return lines


def format_spec_fill_verify_feishu_reason(fill_stats: dict[str, Any] | None) -> str:
    """规格校验填表失败 → 飞书「失效原因」列中文说明（≤500 字）。"""
    from pdd_agent.domain.listing_errors import ListingErrors

    stats = dict(fill_stats or {})
    lines = _collect_issue_lines(stats)

    price_filled = int(stats.get("price_filled") or 0)
    price_total = int(stats.get("price_total") or 0)
    verify_passed = int(stats.get("verify_passed_count") or 0)
    verify_total = int(stats.get("verify_total") or price_total or 0)

    if not lines:
        if price_total:
            return (
                f"规格校验填表未通过：已填{price_filled}/{price_total}，"
                f"回读校验{verify_passed}/{verify_total}"
            )[:500]
        return "规格校验填表未通过"

    max_detail = 8
    if len(lines) > max_detail:
        extra = len(lines) - max_detail
        lines = lines[:max_detail]
        lines.append(f"另有{extra}处类似问题")

    body = ListingErrors.format_numbered(lines)
    if price_filled < price_total:
        body = f"仅填{price_filled}/{price_total}行，{body}"
    elif verify_passed < verify_total:
        body = f"回读校验{verify_passed}/{verify_total}，{body}"
    return ListingErrors.sanitize_feishu_failure_reason(body[:500])
