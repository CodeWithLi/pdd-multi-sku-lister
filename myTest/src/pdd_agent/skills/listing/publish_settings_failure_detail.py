"""提交前满件折扣/运费模板设置失败：生成具体中文说明。"""

from __future__ import annotations

from typing import Any

from pdd_agent.domain.listing_errors import ListingErrors
from pdd_agent.skills.listing.listing_publish_settings import (
    DEFAULT_BULK_DISCOUNT,
    DEFAULT_SHIPPING_TEMPLATE,
)

_BULK_REASON_LABELS: dict[str, str] = {
    "discount_input_not_found": "未找到「满2件折扣」输入框",
    "verify_failed": "满件折扣写入后校验未通过",
    "guard_verify_failed": "满件折扣补填3次后仍未达到目标值",
    "guard_not_started": "满件折扣 Guard 未成功启动补填",
    "bulk_discount_edit_not_found": "未找到满件折扣「修改」按钮",
    "exception": "满件折扣设置异常",
}

_SERVICE_REASON_LABELS: dict[str, str] = {
    "shipping_form_not_ready": "「3 服务与承诺」未展开，运费模板区域不可用",
    "expand_click_not_effective": "点击「展开修改」后运费模板仍不可选",
    "exception": "展开「服务与承诺」区域异常",
}

_SHIPPING_REASON_LABELS: dict[str, str] = {
    "shipping_section_not_ready": "「3 服务与承诺」未就绪，未能设置运费模板",
    "shipping_form_not_ready": "运费模板表单未就绪（可能未点「展开修改」）",
    "service_section_not_found": "页面上未找到「服务与承诺/运费模板」区域",
    "template_not_selected": "未能选中运费模板",
    "verify_failed": "运费模板选择后校验未通过",
    "option_click_failed": "运费模板下拉选项点击失败",
    "playwright_error": "运费模板 Playwright 自动选择失败",
    "exception": "运费模板设置异常",
}


def _join_detail(base: str, *parts: str) -> str:
    extras = [str(p).strip() for p in parts if str(p or "").strip()]
    if not extras:
        return base
    return f"{base}（{'；'.join(extras)}）"


def _describe_bulk_discount(
    bulk: dict[str, Any],
    *,
    target: str = DEFAULT_BULK_DISCOUNT,
) -> str | None:
    if bulk.get("ok"):
        return None
    reason = str(bulk.get("reason") or "").strip()
    guard = str(bulk.get("guard") or "").strip()
    if guard == "fill_failed" or reason == "guard_verify_failed":
        base = _BULK_REASON_LABELS["guard_verify_failed"]
    else:
        base = _BULK_REASON_LABELS.get(reason) or (
            f"满件折扣未设置成功（{reason}）" if reason else "满件折扣未设置成功"
        )

    if reason == "exception":
        err = str(bulk.get("error") or "").strip()
        return _join_detail(base, err) if err else base

    final_state = bulk.get("final_state") if isinstance(bulk.get("final_state"), dict) else {}
    input_val = str(final_state.get("input_value") or bulk.get("after") or "").strip()
    visible_val = str(final_state.get("visible_value") or "").strip()
    before_val = str(bulk.get("before") or "").strip()

    value_parts: list[str] = []
    if input_val:
        value_parts.append(f"输入框={input_val}")
    if visible_val:
        value_parts.append(f"页面显示={visible_val}折")
    if before_val and before_val != input_val:
        value_parts.append(f"原值={before_val}")

    if value_parts:
        return _join_detail(base, f"当前{'，'.join(value_parts)}，目标应为 {target} 折")
    return _join_detail(base, f"目标应为 {target} 折")


def _describe_service_section(service: dict[str, Any]) -> str | None:
    if service.get("ok"):
        return None
    reason = str(service.get("reason") or "").strip()
    base = _SERVICE_REASON_LABELS.get(reason) or (
        f"「3 服务与承诺」区域未就绪（{reason}）" if reason else "「3 服务与承诺」区域未就绪"
    )
    if reason == "exception":
        err = str(service.get("error") or "").strip()
        return _join_detail(base, err) if err else base

    state = service.get("state") if isinstance(service.get("state"), dict) else {}
    extras: list[str] = []
    if state.get("expandButtonVisible"):
        extras.append("仍显示「展开修改」按钮")
    if state.get("formReady") is False:
        extras.append("运费表单未就绪")
    header = str(state.get("headerText") or "").strip()
    if header:
        extras.append(f"下拉框={header}")
    return _join_detail(base, *extras)


def _describe_shipping_template(
    shipping: dict[str, Any],
    service: dict[str, Any],
    *,
    target: str = DEFAULT_SHIPPING_TEMPLATE,
) -> str | None:
    if shipping.get("ok"):
        return None
    reason = str(shipping.get("reason") or shipping.get("step") or "").strip()
    base = _SHIPPING_REASON_LABELS.get(reason) or (
        f"运费模板未设置成功（{reason}）" if reason else "运费模板未设置成功"
    )

    if reason == "exception":
        err = str(shipping.get("error") or "").strip()
        return _join_detail(base, err) if err else base

    if reason == "template_not_selected":
        base = f"未能选中运费模板「{target}」"

    state = shipping.get("state") if isinstance(shipping.get("state"), dict) else {}
    detail = shipping.get("detail") if isinstance(shipping.get("detail"), dict) else {}
    extras: list[str] = []

    current = str(state.get("current") or shipping.get("template") or "").strip()
    if current:
        extras.append(f"当前={current}")
    elif state.get("otherChecked") is False:
        extras.append("「其他模板」未勾选")

    visible = detail.get("visibleOptions") or shipping.get("visibleOptions") or []
    if isinstance(visible, list) and visible:
        opts = "、".join(str(x).strip() for x in visible[:6] if str(x).strip())
        if opts:
            extras.append(f"可见选项={opts}")

    if not service.get("ok") and reason == "shipping_section_not_ready":
        service_hint = _describe_service_section(service)
        if service_hint:
            extras.insert(0, service_hint)

    if extras:
        return _join_detail(base, *extras)
    return _join_detail(base, f"目标模板={target}")


def collect_publish_settings_issues(
    publish_settings: dict[str, Any] | None,
    *,
    bulk_target: str = DEFAULT_BULK_DISCOUNT,
    shipping_target: str = DEFAULT_SHIPPING_TEMPLATE,
) -> list[str]:
    """从 publish_settings 摘要提取具体失败项。"""
    settings = dict(publish_settings or {})
    issues: list[str] = []
    seen: set[str] = set()

    def _add(line: str) -> None:
        text = str(line or "").strip()
        if text and text not in seen:
            seen.add(text)
            issues.append(text)

    bulk = settings.get("bulk_discount") if isinstance(settings.get("bulk_discount"), dict) else {}
    service = settings.get("service_section") if isinstance(settings.get("service_section"), dict) else {}
    shipping = settings.get("shipping_template") if isinstance(settings.get("shipping_template"), dict) else {}

    bulk_issue = _describe_bulk_discount(bulk, target=bulk_target)
    if bulk_issue:
        _add(bulk_issue)

    if not service.get("ok"):
        service_issue = _describe_service_section(service)
        if service_issue and service_issue not in issues:
            _add(service_issue)

    shipping_issue = _describe_shipping_template(shipping, service, target=shipping_target)
    if shipping_issue:
        _add(shipping_issue)

    if not issues:
        _add("提交前设置未完成（满件折扣或运费模板）")
    return issues


def build_publish_settings_failure_detail(
    publish_settings: dict[str, Any] | None,
    *,
    merchant_code: str = "",
    bulk_target: str = DEFAULT_BULK_DISCOUNT,
    shipping_target: str = DEFAULT_SHIPPING_TEMPLATE,
) -> str:
    """拼成飞书一行具体说明。"""
    issues = collect_publish_settings_issues(
        publish_settings,
        bulk_target=bulk_target,
        shipping_target=shipping_target,
    )
    return ListingErrors.format_validation_detail_brief(issues, merchant_code=merchant_code)
