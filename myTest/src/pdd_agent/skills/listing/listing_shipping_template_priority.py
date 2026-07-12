"""运费模板下拉选项优先级：最新全国 > 全国最新。"""

from __future__ import annotations

from typing import Any

DEFAULT_SHIPPING_TEMPLATE = "最新全国"
FALLBACK_SHIPPING_TEMPLATE = "全国最新"

# 按优先级排列；组内从左到右为同优先级别名。
SHIPPING_TEMPLATE_PRIORITY_GROUPS: tuple[tuple[str, ...], ...] = (
    ("最新全国", "最新全网"),
    (FALLBACK_SHIPPING_TEMPLATE,),
)


def _normalize_template_text(text: str) -> str:
    return str(text or "").replace(" ", "").strip()


def iter_shipping_template_selection_attempts() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """返回 [(主名, 别名...), ...]，按选择优先级排序。"""
    return tuple((group[0], group[1:]) for group in SHIPPING_TEMPLATE_PRIORITY_GROUPS)


def flatten_shipping_template_candidates() -> tuple[str, ...]:
    """按优先级展开全部候选名（去重）。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for group in SHIPPING_TEMPLATE_PRIORITY_GROUPS:
        for name in group:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
    return tuple(ordered)


def option_text_matches_template(option_text: str, template_name: str) -> bool:
    """下拉选项文本是否匹配目标模板名（含别名等价）。"""
    normalized_option = _normalize_template_text(option_text)
    normalized_target = _normalize_template_text(template_name)
    if not normalized_option or not normalized_target:
        return False
    if normalized_option == normalized_target:
        return True
    return normalized_target in normalized_option


def resolve_pick_from_visible_options(visible_options: list[str]) -> str | None:
    """从可见下拉项中按优先级解析应选模板名；无匹配返回 None。"""
    for group in SHIPPING_TEMPLATE_PRIORITY_GROUPS:
        for name in group:
            for opt in visible_options:
                if option_text_matches_template(opt, name):
                    return name
    return None


def shipping_state_matches_acceptable(current: str) -> bool:
    """当前选中值是否为可接受的运费模板。"""
    normalized = _normalize_template_text(current)
    if not normalized:
        return False
    for group in SHIPPING_TEMPLATE_PRIORITY_GROUPS:
        for name in group:
            target = _normalize_template_text(name)
            if target and target in normalized:
                return True
    return False


def resolve_matched_template_name(current: str) -> str | None:
    """解析当前值对应的标准模板名（按优先级，返回组内主名）。"""
    for group in SHIPPING_TEMPLATE_PRIORITY_GROUPS:
        for name in group:
            if option_text_matches_template(current, name):
                return group[0]
    return None


def shipping_failure_target_label() -> str:
    """失败提示中使用的目标模板描述（保持与原有报错一致）。"""
    return DEFAULT_SHIPPING_TEMPLATE


def describe_acceptable_templates() -> str:
    primary = "、".join(SHIPPING_TEMPLATE_PRIORITY_GROUPS[0])
    return f"{primary} 或 {FALLBACK_SHIPPING_TEMPLATE}"


def shipping_template_state_summary(state: dict[str, Any] | None) -> dict[str, Any]:
    """从页面状态摘要中提取模板匹配信息。"""
    current = str((state or {}).get("current") or "")
    matched = resolve_matched_template_name(current)
    return {
        "current": current,
        "matched": matched,
        "acceptable": shipping_state_matches_acceptable(current),
    }
