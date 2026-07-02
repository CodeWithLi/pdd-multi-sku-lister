"""PDD发布日志表 — 成功/失败分表写入飞书。

流程：
1. 上架核验成功 → 写入「PDD发布日志表」（按商品链接ID去重）
2. 上架失败/跳过 → 写入「淘宝+拼多多发布日志表（失败）」（简短失败原因，与淘宝共用）
3. 限时限量购 / 活动报名 / 推广 → 按商品链接ID检索成功表记录后 update 对应列
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime
from datetime import time as dt_time
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.domain.listing_errors import ListingErrorCode, ListingErrors
from pdd_agent.integrations.feishu.bitable import (
    FIELD_DATETIME,
    FIELD_NUMBER,
    FIELD_SINGLE_SELECT,
    FIELD_TEXT,
    batch_create_records,
    batch_update_records,
    create_table,
    ensure_fields,
    find_table_id_by_name,
    list_fields,
    map_fields_to_table_names,
    search_records_by_field,
)
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    load_feishu_config,
    save_pdd_upload_failure_table_id_to_config,
    save_pdd_upload_table_id_to_config,
)
from pdd_agent.skills.delist.time_utils import extract_created_at_from_text
from pdd_agent.skills.listing.goods_list_capture import is_plain_goods_template_link

logger = get_logger(__name__)

_WRONG_TABLE_ID_CODES = frozenset({1254004, 1254041})
_INVALID_FILTER_CODES = frozenset({1254018})

# 拼多多商品列表状态 → 飞书「状态」单选选项
_PDD_LIST_STATUS_TO_FEISHU: dict[str, str] = {
    "销售中": "已上架",
    "on_sale": "已上架",
    "listed": "已上架",
    "success": "已上架",
    "已上架": "已上架",
}
_FEISHU_UPLOAD_STATUS_FAILURE = "报错上架失败"
_FEISHU_UPLOAD_STATUS_LISTED = "已上架"
_FEISHU_LIMITED_TIME_SUCCESS = "成功"
_FEISHU_LIMITED_TIME_FAILURE = "失败"

_FEISHU_FAILURE_RECORD_FAIL = ListingErrors.FEISHU_RECORD_FAIL
_FEISHU_FAILURE_RECORD_SKIP = ListingErrors.FEISHU_RECORD_SKIP

_SKIP_LISTING_REASON_CODES = ListingErrors.SKIP_REASON_CODES
_FAIL_LISTING_REASON_CODES = ListingErrors.FAIL_REASON_CODES
FEISHU_FAILURE_REASON_LABELS: dict[str, str] = ListingErrors.FEISHU_LABELS


def _strip_bracket_label_from_message(text: str) -> str:
    raw = str(text or "").strip()
    if raw.startswith("[") and "]" in raw:
        return raw.split("]", 1)[-1].strip(" :：")
    return raw


def _humanize_listing_failure_message(
    *,
    reason_code: str = "",
    message: str = "",
    error: str = "",
    merchant_code: str = "",
) -> str:
    """把机器报错转成飞书失败表的一行短说明（编码+短句，无跳过/套图路径）。"""
    raw = _strip_bracket_label_from_message(str(message or error or "").strip())
    return ListingErrors.compact_feishu_line(
        raw,
        reason_code=str(reason_code or "").strip(),
        merchant_code=str(merchant_code or "").strip(),
    )


def _extract_error_code(raw_error: str) -> str:
    text = str(raw_error or "").strip()
    if not text:
        return "NO_ERROR_CODE"
    patterns = (
        r"(?:error[_\s-]*code|code)\s*[:=]\s*([A-Za-z0-9_.-]+)",
        r'"(?:error[_\s-]*code|code)"\s*:\s*"([^"]+)"',
        r"'(?:error[_\s-]*code|code)'\s*:\s*'([^']+)'",
    )
    for pattern in patterns:
        matched = re.search(pattern, text, flags=re.IGNORECASE)
        if matched:
            code = str(matched.group(1) or "").strip()
            if code:
                return code

    # 兜底：像 preview_not_ready / PARAM_INVALID / 10017 这类可读 token。
    fallback = re.search(r"\b([A-Z][A-Z0-9_]{2,}|[a-z]+(?:_[a-z0-9]+){1,}|[0-9]{4,})\b", text)
    if fallback:
        code = str(fallback.group(1) or "").strip()
        if code:
            return code
    return "NO_ERROR_CODE"


def _infer_listing_error_stage(raw_error: str) -> str:
    text = str(raw_error or "").lower()
    if not text:
        return "未知环节"
    if any(token in text for token in ("preview", "素材", "图片", "video", "主图", "详情图")):
        return "素材准备"
    if any(token in text for token in ("title", "类目", "属性", "brand", "品牌", "基础信息")):
        return "商品基础信息校验"
    if any(token in text for token in ("sku", "price", "库存", "spec", "规格", "weight", "重量")):
        return "SKU组装校验"
    # 营销/活动报名类错误：用于填充营销工具日志报错原因
    if any(
        token in text
        for token in (
            "报名",
            "活动",
            "618",
            "限量",
            "七折",
            "优惠",
            "券",
            "coupon",
            "registration",
            "activity",
        )
    ):
        return "营销工具执行"
    # 投流/推广类错误：用于填充投流数据日志报错原因
    if any(
        token in text
        for token in (
            "投流",
            "推广",
            "计划",
            "预算",
            "ads",
            "campaign",
            "traffic",
        )
    ):
        return "投流执行/接口调用"
    if any(token in text for token in ("timeout", "network", "http", "签名", "token", "permission", "权限", "接口")):
        return "平台接口调用"
    if any(token in text for token in ("bitable", "飞书", "回写", "record", "field", "table_id")):
        return "结果回写"
    return "平台接口调用"


def _explain_listing_error(raw_error: str, error_code: str, stage: str) -> tuple[str, str]:
    text = str(raw_error or "").strip()
    lower = text.lower()
    normalized_code = str(error_code or "").strip().lower()

    if normalized_code == "preview_not_ready" or "preview_not_ready" in lower:
        return (
            "商品预览素材尚未生成完成，系统在预览未就绪时发起了提交流程，平台拒绝受理该商品。",
            "等待1-3分钟后重试；若连续3次仍失败，检查商品主图/详情图处理任务是否卡住并重新触发素材生成。",
        )
    if "param_invalid" in normalized_code or "invalid parameter" in lower:
        return (
            "接口参数校验未通过，通常由价格、库存、类目属性或字段格式不符合平台约束导致。",
            "根据原始报错中的字段名逐项修正（如价格、库存、属性值），修正后重新提交上传。",
        )
    if "category" in lower and ("missing" in lower or "attr" in lower):
        return (
            "类目必填属性缺失或填写不完整，平台在商品基础信息校验阶段拦截了请求。",
            "补齐对应类目的必填属性并保存后重新上传。",
        )
    if "timeout" in lower or "timed out" in lower:
        return (
            "请求在平台接口调用阶段超时，常见于网络波动或平台接口拥堵。",
            "先自动重试；若多次超时，稍后再试并检查本地网络与平台服务状态。",
        )
    if "token" in lower or "签名" in text or "permission" in lower or "权限" in text:
        return (
            "鉴权失败（token、签名或权限不足），平台拒绝当前请求。",
            "检查账号授权状态、接口权限范围以及签名参数是否正确，再重新执行上传。",
        )
    if stage == "结果回写":
        return (
            "对应链路结果已产生，但在写回飞书多维表时失败，导致运营侧看不到最新状态。",
            "检查飞书表字段名与配置是否一致、字段类型是否匹配，并确认当前 token 具备写权限。",
        )
    if stage == "营销工具执行":
        return (
            "营销工具链路返回业务失败：常见原因是活动报名/推广提交的商品不满足条件，或部分参数不符合平台约束。",
            "按原始报错定位具体失败商品/步骤（例如报名提交被拦截、规格不合格、优惠工具参数非法等），修正后重新触发该链路回写。",
        )
    if stage == "投流执行/接口调用":
        return (
            "投流链路返回业务失败：常见原因是计划/预算/出价等参数非法，或投放提交时平台拦截请求。",
            "检查原始报错中的具体参数字段（预算/出价/计划状态等），修正后重新触发该链路回写。",
        )
    return (
        "平台返回了业务错误，当前信息不足以自动归类到更细场景，请按原始报错进行人工修正。",
        "结合原始报错关键字定位具体字段或环节，修正后将人工处理状态改为“已修正”并触发重试。",
    )


def _format_listing_error_reason(raw_error: str) -> str:
    raw = str(raw_error or "").strip()
    if not raw:
        return ""
    error_code = _extract_error_code(raw)
    stage = _infer_listing_error_stage(raw)
    reason_cn, suggestion = _explain_listing_error(raw, error_code, stage)
    # 用固定模板回写，确保运营可以精确看到“哪里报错、怎么导致、怎么修”。
    return (
        f"错误码: {error_code}\n"
        f"错误环节: {stage}\n"
        f"原始报错: {raw}\n"
        f"中文解释: {reason_cn}\n"
        f"修复建议: {suggestion}"
    )


def _format_brief_listing_failure_reason(
    *,
    listing_label: str = "",
    reason_code: str = "",
    error: str = "",
    message: str = "",
    record_type: str = "",
    merchant_code: str = "",
) -> str:
    """失败表失败原因：仅一行短说明，不加跳过/失败/套图路径前缀。"""
    _ = record_type
    label = str(listing_label or "").strip()
    code = str(merchant_code or "").strip()
    if not code and label:
        _, code = parse_listing_label_from_text(label)
    body = _humanize_listing_failure_message(
        reason_code=reason_code,
        message=message,
        error=error,
        merchant_code=code,
    )
    return ListingErrors.sanitize_feishu_failure_reason(body[:500])


def _format_system_failure_reason(
    *,
    reason_code: str = "",
    error: str = "",
    message: str = "",
) -> str:
    """失败表系统原因：保留系统侧细节，便于定位问题来源。"""
    code = str(reason_code or "").strip()
    label = ListingErrors.label(code, fallback=code or "unknown")
    raw = str(message or "").strip() or str(error or "").strip()
    if raw:
        raw = _strip_bracket_label_from_message(raw)
        return f"{label}｜{raw}"[:500]
    return label[:500]


def parse_listing_label_from_text(text: str) -> tuple[str, str]:
    """从报错文本解析 (listing_label, merchant_code)。"""
    raw = str(text or "").strip()
    if not raw:
        return "", ""

    def _merchant_code_from_label(label: str) -> str:
        parts = [p for p in label.split("/") if p]
        if not parts:
            return label
        if len(parts) >= 3:
            return parts[-1]
        if len(parts) == 2:
            # 商品编码/套图，如 BD022A音乐小猫笔袋/第一套图
            return parts[0]
        first = parts[0]
        if re.match(r"^[A-Z0-9]{3,}[A-Z]?$", first, flags=re.IGNORECASE):
            return first
        return parts[0]

    bracket = re.match(r"^\[([^\]]+)\]", raw)
    if bracket:
        label = bracket.group(1).strip()
        return label, _merchant_code_from_label(label)

    for slot_pattern in (
        r"兄弟款规格不齐：([A-Z0-9]{3,}[A-Z]?)",
        r"兄弟款规格图命名错误：([A-Z0-9]{3,}[A-Z]?)",
    ):
        slot = re.search(slot_pattern, raw, flags=re.IGNORECASE)
        if slot:
            return "", slot.group(1).upper()

    fail = re.match(r"^失败:\s*([^:]+):", raw)
    if fail:
        label = fail.group(1).strip()
        if label:
            return label, _merchant_code_from_label(label)

    for sep in ("：子编码", ": 子编码"):
        if sep in raw:
            head = raw.split(sep, 1)[0].strip()
            if "/" in head and len(head) <= 80:
                return head, _merchant_code_from_label(head)

    head = raw.split("：", 1)[0].split(":", 1)[0].strip()
    if "/" in head and len(head) <= 80:
        return head, _merchant_code_from_label(head)
    return "", ""


def map_listing_failure_record_type(
    *,
    status: str = "",
    reason_code: str = "",
    retryable: bool = False,
    legacy_status: str = "",
) -> str:
    status_norm = str(status or "").strip().lower()
    legacy = str(legacy_status or "").strip().lower()
    code = str(reason_code or "").strip()
    if code in _FAIL_LISTING_REASON_CODES or status_norm == "failed":
        return _FEISHU_FAILURE_RECORD_FAIL
    if legacy == "skipped" or retryable or status_norm == "retryable":
        return _FEISHU_FAILURE_RECORD_SKIP
    if code in _SKIP_LISTING_REASON_CODES:
        return _FEISHU_FAILURE_RECORD_SKIP
    return _FEISHU_FAILURE_RECORD_FAIL


def _field_defs_for_pdd_upload_failure_log(config: FeishuConfig) -> list[dict[str, Any]]:
    names = config.pdd_upload_log.failure_field_names
    pdd_cfg = config.pdd_upload_log
    return [
        {"field_name": names.date, "type": FIELD_DATETIME, "property": {"date_formatter": "yyyy/MM/dd", "auto_fill": False}},
        {"field_name": names.merchant_code, "type": FIELD_TEXT},
        {
            "field_name": names.report_platform,
            "type": FIELD_SINGLE_SELECT,
            "property": {"options": [{"name": x} for x in pdd_cfg.failure_report_platform_options]},
        },
        {"field_name": names.account_name, "type": FIELD_TEXT},
        {
            "field_name": names.record_type,
            "type": FIELD_SINGLE_SELECT,
            "property": {"options": [{"name": x} for x in pdd_cfg.failure_record_type_options]},
        },
        {"field_name": names.failure_reason, "type": FIELD_TEXT},
        {"field_name": names.system_reason, "type": FIELD_TEXT},
        {
            "field_name": names.publish_start,
            "type": FIELD_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd HH:mm", "auto_fill": False},
        },
        {
            "field_name": names.publish_end,
            "type": FIELD_DATETIME,
            "property": {"date_formatter": "yyyy/MM/dd HH:mm", "auto_fill": False},
        },
        {
            "field_name": names.duration_seconds,
            "type": FIELD_NUMBER,
            "property": {"formatter": "0.00"},
        },
    ]


def _ensure_pdd_upload_failure_table_fields(
    client: FeishuClient,
    config: FeishuConfig,
    app_token: str,
    table_id: str,
) -> None:
    ensure_fields(client, app_token, table_id, _field_defs_for_pdd_upload_failure_log(config))


def _verify_pdd_table_id(client: FeishuClient, app_token: str, table_id: str) -> bool:
    """校验 table_id 是否仍可访问（已删表会返回 TableIdNotFound）。"""
    table_id = str(table_id or "").strip()
    if not table_id:
        return False
    try:
        list_fields(client, app_token, table_id)
        return True
    except FeishuAPIError as exc:
        if exc.code in _WRONG_TABLE_ID_CODES:
            return False
        raise


def _resolve_or_create_pdd_table_id(
    cfg: FeishuConfig,
    client: FeishuClient,
    *,
    configured_id: str,
    table_name: str,
    save_table_id: bool,
    save_fn: Any,
    create_if_missing: bool = False,
) -> tuple[str, str]:
    app_token = str(cfg.bitable_app_token or "").strip()
    configured = str(configured_id or "").strip()
    name = str(table_name or "").strip()

    if name:
        found = find_table_id_by_name(client, app_token, name)
        if found and _verify_pdd_table_id(client, app_token, found):
            if configured and configured != found:
                logger.warning(
                    "pdd feishu table_id corrected by name: config=%s actual=%s name=%s",
                    configured,
                    found,
                    name,
                )
            if save_table_id and found != configured:
                try:
                    save_fn(found)
                except Exception as exc:
                    logger.warning("save pdd table_id failed name=%s: %s", name, exc)
            return found, "table_name"
        if found and not _verify_pdd_table_id(client, app_token, found):
            logger.warning(
                "pdd feishu table name=%s maps to invalid table_id=%s, will recreate if allowed",
                name,
                found,
            )

    if configured and _verify_pdd_table_id(client, app_token, configured):
        return configured, "config_table_id"
    if configured:
        logger.warning(
            "pdd feishu configured table_id invalid: id=%s name=%s create_if_missing=%s",
            configured,
            name,
            create_if_missing,
        )

    if name and create_if_missing:
        created = create_table(client, app_token, name)
        if save_table_id:
            try:
                save_fn(created)
            except Exception as exc:
                logger.warning("save pdd table_id failed after create name=%s: %s", name, exc)
        logger.info("pdd feishu table created name=%s table_id=%s", name, created)
        return created, "created"

    return "", "missing"


def resolve_pdd_upload_failure_table_id(
    cfg: FeishuConfig,
    client: FeishuClient,
    *,
    save_table_id: bool = True,
    create_if_missing: bool = False,
) -> tuple[str, str]:
    pdd_cfg = cfg.pdd_upload_log
    return _resolve_or_create_pdd_table_id(
        cfg,
        client,
        configured_id=pdd_cfg.failure_table_id,
        table_name=pdd_cfg.failure_table_name,
        save_table_id=save_table_id,
        save_fn=save_pdd_upload_failure_table_id_to_config,
        create_if_missing=create_if_missing,
    )


def ensure_pdd_upload_log_tables_ready(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    """启动或同步前确保 PDD 发布成功/失败两张表存在且字段齐全。"""
    cfg = config or load_feishu_config()
    pdd_cfg = cfg.pdd_upload_log
    if not pdd_cfg.enabled and not pdd_cfg.failure_log_enabled:
        return {"skipped": True, "reason": "pdd_upload_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    api = client or FeishuClient(cfg)
    success_id = ""
    success_method = ""
    if pdd_cfg.enabled:
        success_id, success_method = _resolve_or_create_pdd_table_id(
            cfg,
            api,
            configured_id=pdd_cfg.table_id,
            table_name=pdd_cfg.table_name,
            save_table_id=True,
            save_fn=save_pdd_upload_table_id_to_config,
            create_if_missing=True,
        )
        if not success_id:
            return {
                "failed": True,
                "reason": "success_table_not_found",
                "message": f"未找到或无法创建飞书表「{pdd_cfg.table_name}」",
            }
        _ensure_pdd_upload_table_fields(api, cfg, app_token, success_id)

    failure_id = ""
    failure_method = ""
    if pdd_cfg.failure_log_enabled:
        failure_id, failure_method = resolve_pdd_upload_failure_table_id(
            cfg, api, save_table_id=True, create_if_missing=True
        )
        if not failure_id:
            return {
                "failed": True,
                "reason": "failure_table_not_found",
                "message": f"未找到或无法创建飞书表「{pdd_cfg.failure_table_name}」",
            }
        _ensure_pdd_upload_failure_table_fields(api, cfg, app_token, failure_id)

    return {
        "ready": True,
        "success_table_id": success_id,
        "success_resolve_method": success_method,
        "failure_table_id": failure_id,
        "failure_resolve_method": failure_method,
    }


def build_pdd_upload_failure_log_fields(
    *,
    config: FeishuConfig,
    merchant_code: str,
    account_name: str,
    account_id: str = "",
    record_type: str,
    failure_reason: str,
    system_reason: str = "",
    report_platform: str = "",
    publish_start: datetime | None = None,
    publish_end: datetime | None = None,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    names = config.pdd_upload_log.failure_field_names
    pdd_cfg = config.pdd_upload_log
    end_at = publish_end or datetime.now()
    start_at = publish_start or end_at
    duration = duration_seconds
    if duration is None:
        duration = max(0.0, (end_at - start_at).total_seconds())

    platform = str(report_platform or pdd_cfg.failure_default_report_platform or "拼多多").strip() or "拼多多"

    fields: dict[str, Any] = {
        names.date: _date_to_ms(end_at.date()),
        names.merchant_code: str(merchant_code or "").strip(),
        names.report_platform: platform,
        names.account_name: str(account_name or "").strip(),
        names.record_type: str(record_type or _FEISHU_FAILURE_RECORD_FAIL).strip(),
        names.failure_reason: ListingErrors.sanitize_feishu_failure_reason(
            str(failure_reason or "").strip()
        )[:500],
        names.system_reason: ListingErrors.sanitize_feishu_failure_reason(
            str(system_reason or "").strip()
        )[:2000],
        names.publish_start: _ms_timestamp(start_at),
        names.publish_end: _ms_timestamp(end_at),
        names.duration_seconds: round(float(duration), 2),
    }
    account_id_field = str(getattr(names, "account_id", "") or "").strip()
    if account_id_field:
        fields[account_id_field] = str(account_id or "").strip()
    return fields


def push_pdd_upload_failure_log(
    *,
    account_id: str = "",
    account_name: str = "",
    listing_label: str = "",
    merchant_code: str = "",
    record_type: str = "",
    reason_code: str = "",
    failure_reason: str = "",
    system_reason: str = "",
    error: str = "",
    message: str = "",
    publish_start: datetime | None = None,
    publish_end: datetime | None = None,
    duration_seconds: float | None = None,
    report_platform: str = "",
    fallback_product_code: str = "",
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    pdd_cfg = cfg.pdd_upload_log
    if not pdd_cfg.failure_log_enabled:
        return {"skipped": True, "reason": "failure_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    code = str(merchant_code or "").strip()
    label = str(listing_label or "").strip()
    raw_msg = str(message or error or failure_reason or "").strip()
    if not code and not label and raw_msg:
        label, code = parse_listing_label_from_text(raw_msg)
    if not code and not label:
        code = str(fallback_product_code or "").strip() or "未知"

    record_type_value = str(record_type or "").strip() or map_listing_failure_record_type(
        reason_code=reason_code,
        retryable=False,
    )
    store_name = str(account_name or account_id or "").strip()
    if code and "/" in code:
        _, code = parse_listing_label_from_text(code)
    if not code and label:
        _, code = parse_listing_label_from_text(label)

    brief = str(failure_reason or "").strip() or _format_brief_listing_failure_reason(
        listing_label=label,
        reason_code=reason_code,
        error=error,
        message=message,
        record_type=record_type_value,
        merchant_code=code,
    )
    system_reason_text = str(system_reason or "").strip() or _format_system_failure_reason(
        reason_code=reason_code,
        error=error,
        message=message,
    )

    fields = build_pdd_upload_failure_log_fields(
        config=cfg,
        merchant_code=code or "",
        account_name=store_name,
        account_id=str(account_id or "").strip(),
        record_type=record_type_value,
        failure_reason=brief,
        system_reason=system_reason_text,
        report_platform=report_platform,
        publish_start=publish_start,
        publish_end=publish_end,
        duration_seconds=duration_seconds,
    )

    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_pdd_upload_failure_table_id(cfg, api)
    if not table_id:
        msg = f"未找到飞书表「{pdd_cfg.failure_table_name}」，请检查 bitable_app_token 与表名"
        logger.error("feishu pdd upload failure log failed: %s", msg)
        return {"failed": True, "reason": "table_not_found", "message": msg}
    _ensure_pdd_upload_failure_table_fields(api, cfg, app_token, table_id)
    fields = map_fields_to_table_names(api, app_token, table_id, fields)

    try:
        record_ids = batch_create_records(api, app_token, table_id, [fields])
    except FeishuAPIError as exc:
        if exc.code in _WRONG_TABLE_ID_CODES:
            table_id, resolve_method = resolve_pdd_upload_failure_table_id(
                cfg, api, save_table_id=True, create_if_missing=True
            )
            if not table_id:
                raise
            _ensure_pdd_upload_failure_table_fields(api, cfg, app_token, table_id)
            fields = map_fields_to_table_names(api, app_token, table_id, fields)
            record_ids = batch_create_records(api, app_token, table_id, [fields])
        else:
            raise

    logger.info(
        "[%s] feishu pdd upload failure log created label=%s record_id=%s table=%s(%s)",
        account_id or "-",
        label or code,
        record_ids[0] if record_ids else "",
        table_id,
        resolve_method,
    )
    return {
        "created": True,
        "table_id": table_id,
        "resolve_method": resolve_method,
        "record_ids": record_ids,
        "fields": fields,
    }


def _pdd_upload_dedupe_field(config: FeishuConfig) -> str:
    names = config.pdd_upload_log.field_names
    return str(
        config.pdd_upload_log.dedupe_field or names.link_product_id or "商品链接ID"
    ).strip()


def _field_defs_for_pdd_upload_log(config: FeishuConfig) -> list[dict[str, Any]]:
    names = config.pdd_upload_log.field_names
    datetime_prop = {"date_formatter": "yyyy/MM/dd HH:mm", "auto_fill": False}
    return [
        {"field_name": names.date, "type": FIELD_DATETIME, "property": {"date_formatter": "yyyy/MM/dd", "auto_fill": False}},
        {"field_name": names.merchant_code, "type": FIELD_TEXT},
        {"field_name": names.combo_barcode, "type": FIELD_TEXT},
        {"field_name": names.title, "type": FIELD_TEXT},
        {"field_name": names.account_name, "type": FIELD_TEXT},
        {"field_name": names.link_product_id, "type": FIELD_TEXT},
        {"field_name": names.group_price, "type": FIELD_NUMBER},
        {"field_name": names.single_sell_price, "type": FIELD_NUMBER},
        {"field_name": names.link, "type": 15},
        {"field_name": names.publish_start, "type": FIELD_DATETIME, "property": datetime_prop},
        {"field_name": names.publish_end, "type": FIELD_DATETIME, "property": datetime_prop},
        {
            "field_name": names.duration_seconds,
            "type": FIELD_NUMBER,
            "property": {"formatter": "0.00"},
        },
    ]


def _ensure_pdd_upload_table_fields(client: FeishuClient, config: FeishuConfig, app_token: str, table_id: str) -> None:
    ensure_fields(client, app_token, table_id, _field_defs_for_pdd_upload_log(config))


def extract_product_ids_for_limited_time_status(
    product_ids: list[str] | None,
    result: dict[str, Any] | None,
) -> list[str]:
    ids = list(dict.fromkeys(str(pid or "").strip() for pid in (product_ids or []) if str(pid or "").strip()))
    if ids:
        return ids
    payload = result if isinstance(result, dict) else {}
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        for pid in item.get("selected_pdd_product_ids") or []:
            text = str(pid or "").strip()
            if text:
                ids.append(text)
    return list(dict.fromkeys(ids))


def map_limited_time_status_to_feishu(*, success: bool) -> str:
    return _FEISHU_LIMITED_TIME_SUCCESS if success else _FEISHU_LIMITED_TIME_FAILURE


def map_activity_register_status_to_feishu(*, success: bool) -> str:
    return map_limited_time_status_to_feishu(success=success)


def map_promotion_status_to_feishu(*, success: bool) -> str:
    return map_limited_time_status_to_feishu(success=success)


def resolve_activity_register_field_name(activity_id: str, config: FeishuConfig | None = None) -> str:
    cfg = config or load_feishu_config()
    pdd_cfg = cfg.pdd_upload_log
    aid = str(activity_id or "").strip()
    if not aid:
        return ""
    mapped = pdd_cfg.activity_register_fields.get(aid)
    return str(mapped or "").strip()


def extract_product_ids_from_campaign_result(
    product_ids: list[str] | None,
    result: dict[str, Any] | None,
) -> list[str]:
    return extract_product_ids_for_limited_time_status(product_ids, result)


def _find_pdd_upload_record_by_product_id(
    client: FeishuClient,
    *,
    app_token: str,
    table_id: str,
    dedupe_field: str,
    product_id: str,
    retries: int,
    interval_seconds: float,
) -> dict[str, Any] | None:
    product_id = str(product_id or "").strip()
    if not product_id:
        return None
    attempts = max(1, int(retries))
    for attempt in range(attempts):
        try:
            rows = search_records_by_field(
                client,
                app_token,
                table_id,
                field_name=dedupe_field,
                value=product_id,
            )
        except FeishuAPIError as exc:
            if exc.code in _INVALID_FILTER_CODES:
                logger.warning(
                    "feishu limited time status lookup skipped invalid filter field=%s product_id=%s",
                    dedupe_field,
                    product_id,
                )
                return None
            raise
        if rows:
            return rows[0]
        if attempt + 1 < attempts:
            time.sleep(max(0.5, float(interval_seconds)))
    return None


def _coerce_bitable_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value).strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict) and item.get("text") is not None:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "".join(parts).strip()
    if isinstance(value, dict) and value.get("text") is not None:
        return str(value["text"]).strip()
    return str(value).strip()


def lookup_pdd_upload_log_identity_fields(
    product_id: str,
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    retries: int | None = None,
    interval_seconds: float | None = None,
) -> dict[str, str]:
    """从 PDD发布日志表读取商品标识（供 PDD活动日志表建行的上下文）。"""
    pid = str(product_id or "").strip()
    if not pid:
        return {}
    cfg = config or load_feishu_config()
    pdd_cfg = cfg.pdd_upload_log
    if not pdd_cfg.enabled:
        return {}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {}

    api = client or FeishuClient(cfg)
    table_id, _ = resolve_pdd_upload_table_id(cfg, api, save_table_id=False, create_if_missing=False)
    if not table_id:
        return {}

    dedupe_field = _pdd_upload_dedupe_field(pdd_cfg)
    upload_names = pdd_cfg.field_names
    lookup_retries = max(1, int(retries if retries is not None else pdd_cfg.limited_time_lookup_retries))
    lookup_interval = max(
        0.5,
        float(interval_seconds if interval_seconds is not None else pdd_cfg.limited_time_lookup_interval_seconds),
    )
    row = _find_pdd_upload_record_by_product_id(
        api,
        app_token=app_token,
        table_id=table_id,
        dedupe_field=dedupe_field,
        product_id=pid,
        retries=lookup_retries,
        interval_seconds=lookup_interval,
    )
    if not row:
        return {}

    fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
    return {
        "merchant_code": _coerce_bitable_text(fields.get(upload_names.merchant_code)),
        "title": _coerce_bitable_text(fields.get(upload_names.title)),
        "account_name": _coerce_bitable_text(fields.get(upload_names.account_name)),
        "product_link": _coerce_bitable_text(fields.get(upload_names.link)),
    }


def _push_pdd_upload_select_field_by_product_ids(
    *,
    account_id: str = "",
    product_ids: list[str],
    status_field: str,
    status_value: str,
    log_label: str,
    error: str = "",
    extra_fields: dict[str, Any] | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    pdd_cfg = cfg.pdd_upload_log
    if not pdd_cfg.enabled:
        return {"skipped": True, "reason": "pdd_upload_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    ids = list(dict.fromkeys(str(pid or "").strip() for pid in product_ids if str(pid or "").strip()))
    if not ids:
        return {"skipped": True, "reason": "missing_product_ids"}

    field_name = str(status_field or "").strip()
    if not field_name:
        return {"skipped": True, "reason": "missing_status_field"}

    dedupe_field = _pdd_upload_dedupe_field(pdd_cfg)
    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_pdd_upload_table_id(cfg, api)
    if not table_id:
        msg = f"未找到飞书表「{pdd_cfg.table_name}」"
        logger.error("feishu %s failed: %s", log_label, msg)
        return {"failed": True, "reason": "table_not_found", "message": msg}
    _ensure_pdd_upload_table_fields(api, cfg, app_token, table_id)

    updates: list[dict[str, Any]] = []
    missing: list[str] = []
    for product_id in ids:
        row = _find_pdd_upload_record_by_product_id(
            api,
            app_token=app_token,
            table_id=table_id,
            dedupe_field=dedupe_field,
            product_id=product_id,
            retries=pdd_cfg.limited_time_lookup_retries,
            interval_seconds=pdd_cfg.limited_time_lookup_interval_seconds,
        )
        if not row:
            missing.append(product_id)
            continue
        record_id = str(row.get("record_id") or "").strip()
        if not record_id:
            missing.append(product_id)
            continue
        merged_fields = {field_name: status_value}
        if isinstance(extra_fields, dict):
            merged_fields.update(extra_fields)
        fields = map_fields_to_table_names(api, app_token, table_id, merged_fields)
        updates.append({"record_id": record_id, "fields": fields})

    updated_ids: list[str] = []
    if updates:
        try:
            batch_update_records(api, app_token, table_id, updates)
            updated_ids = [item["record_id"] for item in updates]
        except FeishuAPIError as exc:
            if exc.code in _WRONG_TABLE_ID_CODES:
                table_id, resolve_method = resolve_pdd_upload_table_id(cfg, api, save_table_id=True)
                if table_id:
                    batch_update_records(api, app_token, table_id, updates)
                    updated_ids = [item["record_id"] for item in updates]
                else:
                    raise
            else:
                raise

    context = (
        f"account={account_id or '-'} field={field_name} status={status_value} "
        f"updated={len(updated_ids)} missing={len(missing)} table={table_id}({resolve_method})"
    )
    if error:
        context += f" error={error[:120]}"
    logger.info("feishu %s push %s", log_label, context)
    print(f"[{account_id or '-'}] 飞书{log_label}：{context}", flush=True)

    return {
        "updated": bool(updated_ids),
        "status": status_value,
        "status_field": field_name,
        "table_id": table_id,
        "record_ids": updated_ids,
        "product_ids": ids,
        "missing_product_ids": missing,
    }


def push_pdd_upload_limited_time_status(
    *,
    account_id: str = "",
    product_ids: list[str],
    success: bool,
    error: str = "",
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    """按商品链接ID更新飞书「限时限量购状态」单选字段。"""
    cfg = config or load_feishu_config()
    pdd_cfg = cfg.pdd_upload_log
    if not pdd_cfg.enabled or not pdd_cfg.update_limited_time_status:
        return {"skipped": True, "reason": "limited_time_status_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    ids = list(dict.fromkeys(str(pid or "").strip() for pid in product_ids if str(pid or "").strip()))
    if not ids:
        return {"skipped": True, "reason": "missing_product_ids"}

    status_value = map_limited_time_status_to_feishu(success=success)
    status_field = "限时限量购状态"

    return _push_pdd_upload_select_field_by_product_ids(
        account_id=account_id,
        product_ids=ids,
        status_field=status_field,
        status_value=status_value,
        log_label="限时限量购状态",
        error=error,
        config=cfg,
        client=client,
    )


def push_pdd_upload_activity_register_status(
    *,
    account_id: str = "",
    activity_id: str,
    product_ids: list[str],
    success: bool,
    error: str = "",
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    """按商品链接ID更新飞书活动报名列（20981→618报名，21365→21365限量七折）。"""
    cfg = config or load_feishu_config()
    pdd_cfg = cfg.pdd_upload_log
    if not pdd_cfg.enabled or not pdd_cfg.update_activity_register_status:
        return {"skipped": True, "reason": "activity_register_status_disabled"}

    status_field = resolve_activity_register_field_name(activity_id, cfg)
    if not status_field:
        return {"skipped": True, "reason": "activity_not_configured", "activity_id": activity_id}

    status_value = map_activity_register_status_to_feishu(success=success)
    return _push_pdd_upload_select_field_by_product_ids(
        account_id=account_id,
        product_ids=product_ids,
        status_field=status_field,
        status_value=status_value,
        log_label=f"活动报名({activity_id})",
        error=error,
        config=cfg,
        client=client,
    )


def push_pdd_upload_promotion_status(
    *,
    account_id: str = "",
    product_ids: list[str],
    success: bool,
    error: str = "",
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    """按商品链接ID更新飞书「推广状态」单选字段。"""
    cfg = config or load_feishu_config()
    pdd_cfg = cfg.pdd_upload_log
    if not pdd_cfg.enabled or not pdd_cfg.update_promotion_status:
        return {"skipped": True, "reason": "promotion_status_disabled"}

    status_field = "推广状态"
    status_value = map_promotion_status_to_feishu(success=success)
    return _push_pdd_upload_select_field_by_product_ids(
        account_id=account_id,
        product_ids=product_ids,
        status_field=status_field,
        status_value=status_value,
        log_label="推广状态",
        error=error,
        config=cfg,
        client=client,
    )


def _push_pdd_upload_field_status_safe(*, log_label: str, push_fn: Any, **kwargs: Any) -> None:
    account_id = str(kwargs.get("account_id") or "")
    try:
        result = push_fn(**kwargs)
        if result.get("updated"):
            missing = result.get("missing_product_ids") or []
            if missing:
                print(
                    f"[{account_id}] 飞书{log_label}已更新 {len(result.get('record_ids') or [])} 条，"
                    f"未找到记录的商品链接ID：{', '.join(missing)}",
                    flush=True,
                )
        elif result.get("skipped"):
            logger.info("feishu %s skipped: %s", log_label, result.get("reason"))
        elif result.get("failed"):
            print(f"[{account_id}] 飞书{log_label}失败：{result.get('message')}", flush=True)
    except Exception as exc:
        logger.exception("feishu %s failed account=%s", log_label, account_id)
        print(f"[{account_id}] 飞书{log_label}失败：{exc}", flush=True)


def _push_pdd_upload_limited_time_status_safe(**kwargs: Any) -> None:
    _push_pdd_upload_field_status_safe(
        log_label="限时限量购状态",
        push_fn=push_pdd_upload_limited_time_status,
        **kwargs,
    )


def _push_pdd_upload_activity_register_status_safe(**kwargs: Any) -> None:
    _push_pdd_upload_field_status_safe(
        log_label="活动报名状态",
        push_fn=push_pdd_upload_activity_register_status,
        **kwargs,
    )


def _push_pdd_upload_promotion_status_safe(**kwargs: Any) -> None:
    _push_pdd_upload_field_status_safe(
        log_label="推广状态",
        push_fn=push_pdd_upload_promotion_status,
        **kwargs,
    )


def schedule_pdd_upload_limited_time_status(**kwargs: Any) -> None:
    """限时限量购完成后回写飞书状态；失败同步写入确保落表。"""
    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.pdd_upload_log.enabled or not cfg.pdd_upload_log.update_limited_time_status:
        return

    if not bool(kwargs.get("success")):
        _push_pdd_upload_limited_time_status_safe(**kwargs)
        return

    thread = threading.Thread(
        target=_push_pdd_upload_limited_time_status_safe,
        kwargs=kwargs,
        name="feishu-pdd-limited-time-status",
        daemon=True,
    )
    thread.start()


def schedule_pdd_upload_activity_register_status(**kwargs: Any) -> None:
    """活动报名完成后回写飞书对应活动列；失败同步写入确保落表。"""
    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.pdd_upload_log.enabled or not cfg.pdd_upload_log.update_activity_register_status:
        return
    activity_id = str(kwargs.get("activity_id") or "").strip()
    if not resolve_activity_register_field_name(activity_id, cfg):
        return

    if not bool(kwargs.get("success")):
        _push_pdd_upload_activity_register_status_safe(**kwargs)
        return

    thread = threading.Thread(
        target=_push_pdd_upload_activity_register_status_safe,
        kwargs=kwargs,
        name="feishu-pdd-activity-register-status",
        daemon=True,
    )
    thread.start()


def schedule_pdd_upload_promotion_status(**kwargs: Any) -> None:
    """推广任务完成后回写飞书「推广状态」；失败同步写入确保落表。"""
    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.pdd_upload_log.enabled or not cfg.pdd_upload_log.update_promotion_status:
        return

    if not bool(kwargs.get("success")):
        _push_pdd_upload_promotion_status_safe(**kwargs)
        return

    thread = threading.Thread(
        target=_push_pdd_upload_promotion_status_safe,
        kwargs=kwargs,
        name="feishu-pdd-promotion-status",
        daemon=True,
    )
    thread.start()


def map_pdd_upload_status_to_feishu(list_status: str) -> str:
    """将拼多多列表状态映射为飞书 PDD 上传日志「状态」单选值。"""
    raw = str(list_status or "").strip()
    if not raw:
        return _FEISHU_UPLOAD_STATUS_LISTED
    mapped = _PDD_LIST_STATUS_TO_FEISHU.get(raw)
    if mapped:
        return mapped
    lower = raw.lower()
    if lower in _PDD_LIST_STATUS_TO_FEISHU:
        return _PDD_LIST_STATUS_TO_FEISHU[lower]
    if raw in {_FEISHU_UPLOAD_STATUS_LISTED, _FEISHU_UPLOAD_STATUS_FAILURE}:
        return raw
    if any(token in raw for token in ("失败", "驳回", "error", "failed")):
        return _FEISHU_UPLOAD_STATUS_FAILURE
    return _FEISHU_UPLOAD_STATUS_LISTED


def _ms_timestamp(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _date_to_ms(day: date) -> int:
    return _ms_timestamp(datetime.combine(day, dt_time.min))


def _parse_created_at(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    dt = extract_created_at_from_text(text)
    if dt:
        return dt
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _link_source_label(product_link: str, product_link_method: str, *, used_fallback: bool) -> str:
    method = str(product_link_method or "").strip()
    if method and method not in {
        "fallback_template",
        "fallback_non_template",
        "not_found",
        "click_failed",
        "empty_product_id",
        "modal_empty",
    }:
        if method.startswith(("playwright_", "js_", "dp_ele_", "modal_", "clipboard")):
            return f"弹窗抓取({method})"
        return f"弹窗抓取({method})"
    if used_fallback:
        return "模板拼接(fallback)"
    if product_link:
        return "已有链接"
    return "无链接"


def format_pdd_upload_log_context(
    *,
    account_id: str = "",
    listing_label: str = "",
    title: str = "",
    merchant_code: str = "",
    product_id: str = "",
    product_link: str = "",
    product_link_method: str = "",
    list_status: str = "",
    created_at_raw: str = "",
    verified_at: datetime | None = None,
    used_link_fallback: bool = False,
) -> str:
    verified = verified_at or datetime.now()
    feishu_status = map_pdd_upload_status_to_feishu(list_status or "销售中")
    link = str(product_link or "").strip() or "(空)"
    if len(link) > 72:
        link = f"{link[:69]}..."
    return (
        f"account={account_id or '-'} label={listing_label or merchant_code or '-'} "
        f"product_id={product_id or '-'} merchant_code={merchant_code or '-'} "
        f"title={title or '-'} status={feishu_status} "
        f"list_status={list_status or '销售中'} "
        f"created_at={created_at_raw or '-'} verified_at={verified.strftime('%Y-%m-%d %H:%M:%S')} "
        f"link_source={_link_source_label(product_link, product_link_method, used_fallback=used_link_fallback)} "
        f"link={link}"
    )


def _resolve_account_display_name(account_id: str) -> str:
    from pdd_agent.core.account_display import resolve_account_display_name

    return resolve_account_display_name(account_id)


def build_pdd_upload_log_fields(
    *,
    config: FeishuConfig,
    title: str,
    merchant_code: str,
    product_id: str,
    product_link: str,
    account_name: str = "",
    combo_barcode: str = "",
    group_price: str | float = "",
    single_price: str | float = "",
    publish_start: datetime | None = None,
    publish_end: datetime | None = None,
    verified_at: datetime,
    created_at_raw: str = "",
) -> dict[str, Any]:
    names = config.pdd_upload_log.field_names
    end_at = publish_end or verified_at
    start_at = publish_start or _parse_created_at(created_at_raw) or end_at
    duration = max(0.0, (end_at - start_at).total_seconds())
    link = str(product_link or "").strip()
    if link and product_id and is_plain_goods_template_link(link, product_id):
        link = ""

    fields: dict[str, Any] = {
        names.date: _date_to_ms(end_at.date()),
        names.merchant_code: str(merchant_code or "").strip(),
        names.title: str(title or "").strip(),
        names.account_name: str(account_name or "").strip(),
        names.publish_start: _ms_timestamp(start_at),
        names.publish_end: _ms_timestamp(end_at),
        names.duration_seconds: round(duration, 2),
    }
    pid = str(product_id or "").strip()
    if pid and names.link_product_id:
        fields[names.link_product_id] = pid
    combo = str(combo_barcode or "").strip()
    if combo and names.combo_barcode:
        fields[names.combo_barcode] = combo
    group = str(group_price or "").strip()
    single = str(single_price or "").strip()
    if group and names.group_price:
        try:
            fields[names.group_price] = float(group)
        except (TypeError, ValueError):
            fields[names.group_price] = group
    if single and names.single_sell_price:
        try:
            fields[names.single_sell_price] = float(single)
        except (TypeError, ValueError):
            fields[names.single_sell_price] = single
    if link:
        fields[names.link] = {"link": link, "text": "查看商品"}
    return fields


def resolve_pdd_upload_table_id(
    cfg: FeishuConfig,
    client: FeishuClient,
    *,
    save_table_id: bool = True,
) -> tuple[str, str]:
    """按表名优先解析 PDD 发布成功日志 table_id，返回 (table_id, method)。"""
    pdd_cfg = cfg.pdd_upload_log
    return _resolve_or_create_pdd_table_id(
        cfg,
        client,
        configured_id=pdd_cfg.table_id,
        table_name=pdd_cfg.table_name,
        save_table_id=save_table_id,
        save_fn=save_pdd_upload_table_id_to_config,
        create_if_missing=False,
    )


def _field_text_from_record(fields: dict[str, Any], field_name: str) -> str:
    if not field_name:
        return ""
    value = fields.get(field_name)
    if value is None:
        return ""
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("text") or first.get("name") or "").strip()
        return str(first).strip()
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or "").strip()
    return str(value).strip()


def _find_upload_log_record_for_row(
    existing_rows: list[dict[str, Any]],
    *,
    combo_field: str,
    combo_barcode: str,
) -> dict[str, Any] | None:
    target_combo = str(combo_barcode or "").strip().upper()
    for item in existing_rows:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        current = _field_text_from_record(fields, combo_field).upper()
        if target_combo:
            if current == target_combo:
                return item
        elif not current:
            return item
    return None


def _upsert_pdd_upload_log_rows(
    *,
    cfg: FeishuConfig,
    api: FeishuClient,
    app_token: str,
    table_id: str,
    resolve_method: str,
    account_id: str,
    listing_label: str,
    product_id: str,
    row_field_list: list[dict[str, Any]],
    product_link_method: str = "",
    used_link_fallback: bool = False,
    effective_link: str = "",
) -> dict[str, Any]:
    names = cfg.pdd_upload_log.field_names
    combo_field = str(names.combo_barcode or "组合商品条码").strip()
    dedupe_field = _pdd_upload_dedupe_field(cfg)

    try:
        existing_rows = search_records_by_field(
            api,
            app_token,
            table_id,
            field_name=dedupe_field,
            value=product_id,
        )
    except FeishuAPIError as exc:
        if exc.code in _INVALID_FILTER_CODES:
            existing_rows = []
        else:
            raise

    created_ids: list[str] = []
    updated_ids: list[str] = []
    stored_fields: list[dict[str, Any]] = []
    to_create: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []

    for raw_fields in row_field_list:
        mapped = map_fields_to_table_names(api, app_token, table_id, raw_fields)
        combo = _field_text_from_record(mapped, combo_field)
        match = _find_upload_log_record_for_row(
            existing_rows,
            combo_field=combo_field,
            combo_barcode=combo,
        )
        if match and match.get("record_id"):
            to_update.append({"record_id": str(match["record_id"]), "fields": mapped})
        else:
            to_create.append(mapped)
        stored_fields.append(mapped)

    if to_update:
        batch_update_records(api, app_token, table_id, to_update)
        updated_ids.extend(str(item["record_id"]) for item in to_update)
    if to_create:
        created_ids.extend(batch_create_records(api, app_token, table_id, to_create))

    logger.info(
        "[%s] feishu pdd upload log upsert product_id=%s created=%s updated=%s table=%s(%s)",
        account_id or "-",
        product_id,
        len(created_ids),
        len(updated_ids),
        table_id,
        resolve_method,
    )
    return {
        "created": bool(created_ids),
        "updated": bool(updated_ids),
        "product_id": product_id,
        "table_id": table_id,
        "resolve_method": resolve_method,
        "record_ids": created_ids + updated_ids,
        "fields": stored_fields[0] if len(stored_fields) == 1 else stored_fields,
        "row_count": len(stored_fields),
        "link_source": _link_source_label(
            effective_link,
            product_link_method,
            used_fallback=used_link_fallback,
        ),
    }


def push_pdd_upload_log(
    *,
    account_id: str = "",
    listing_label: str = "",
    title: str,
    merchant_code: str,
    product_id: str,
    product_link: str = "",
    product_link_method: str = "",
    account_name: str = "",
    publish_start: datetime | None = None,
    publish_end: datetime | None = None,
    list_status: str = "",
    created_at_raw: str = "",
    verified_at: datetime | None = None,
    listing_result: str = "",
    listing_error_reason: str = "",
    chain_phase: str = "listing",
    sku_rows: list[dict[str, Any]] | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    pdd_cfg = cfg.pdd_upload_log
    if not pdd_cfg.enabled:
        return {"skipped": True, "reason": "pdd_upload_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    product_id = str(product_id or "").strip()
    merchant_code = str(merchant_code or "").strip()
    listing_result_norm = str(listing_result or "").strip()
    if listing_result_norm == _FEISHU_LIMITED_TIME_FAILURE or listing_result_norm == "失败":
        return {"skipped": True, "reason": "failure_routed_to_failure_table"}
    if not product_id:
        return {"skipped": True, "reason": "missing_product_id"}

    verified = verified_at or datetime.now()
    effective_account_name = str(account_name or "").strip() or _resolve_account_display_name(account_id)
    effective_publish_end = publish_end or verified
    effective_publish_start = publish_start or _parse_created_at(created_at_raw) or effective_publish_end
    raw_link = str(product_link or "").strip()
    if raw_link and is_plain_goods_template_link(raw_link, product_id):
        raw_link = ""
    used_link_fallback = False
    effective_link = raw_link

    context = format_pdd_upload_log_context(
        account_id=account_id,
        listing_label=listing_label,
        title=title,
        merchant_code=merchant_code,
        product_id=product_id,
        product_link=effective_link,
        product_link_method=product_link_method,
        list_status=list_status,
        created_at_raw=created_at_raw,
        verified_at=verified,
        used_link_fallback=used_link_fallback,
    )
    logger.info("feishu pdd upload log push start %s", context)
    print(f"[{account_id or '-'}] [{listing_label or merchant_code}] 飞书写入准备：{context}", flush=True)

    from pdd_agent.integrations.feishu.pdd_upload_spec_log import (
        build_pdd_upload_spec_log_rows,
        log_spec_sku_rows_enabled,
    )

    spec_rows_payload: list[dict[str, Any]] | None = None
    if log_spec_sku_rows_enabled(cfg) and sku_rows:
        spec_rows_payload = build_pdd_upload_spec_log_rows(
            merchant_code=merchant_code,
            listing_title=title,
            sku_rows=sku_rows,
        )

    if spec_rows_payload:
        row_fields_list = [
            build_pdd_upload_log_fields(
                config=cfg,
                title=str(row.get("title") or title),
                merchant_code=str(row.get("merchant_code") or merchant_code),
                product_id=product_id,
                product_link=effective_link,
                account_name=effective_account_name,
                combo_barcode=str(row.get("combo_barcode") or ""),
                group_price=str(row.get("group_price") or ""),
                single_price=str(row.get("single_price") or ""),
                publish_start=effective_publish_start,
                publish_end=effective_publish_end,
                verified_at=verified,
                created_at_raw=created_at_raw,
            )
            for row in spec_rows_payload
        ]
        api = client or FeishuClient(cfg)
        table_id, resolve_method = resolve_pdd_upload_table_id(cfg, api)
        if not table_id:
            msg = f"未找到飞书表「{pdd_cfg.table_name}」，请检查 bitable_app_token 与表名"
            logger.error("feishu pdd upload log failed: %s", msg)
            return {"failed": True, "reason": "table_not_found", "message": msg}
        _ensure_pdd_upload_table_fields(api, cfg, app_token, table_id)
        try:
            return _upsert_pdd_upload_log_rows(
                cfg=cfg,
                api=api,
                app_token=app_token,
                table_id=table_id,
                resolve_method=resolve_method,
                account_id=account_id,
                listing_label=listing_label,
                product_id=product_id,
                row_field_list=row_fields_list,
                product_link_method=product_link_method,
                used_link_fallback=used_link_fallback,
                effective_link=effective_link,
            )
        except FeishuAPIError as exc:
            if exc.code not in _WRONG_TABLE_ID_CODES:
                raise
            table_id, resolve_method = resolve_pdd_upload_table_id(cfg, api, save_table_id=True)
            if not table_id:
                raise
            _ensure_pdd_upload_table_fields(api, cfg, app_token, table_id)
            return _upsert_pdd_upload_log_rows(
                cfg=cfg,
                api=api,
                app_token=app_token,
                table_id=table_id,
                resolve_method=resolve_method,
                account_id=account_id,
                listing_label=listing_label,
                product_id=product_id,
                row_field_list=row_fields_list,
                product_link_method=product_link_method,
                used_link_fallback=used_link_fallback,
                effective_link=effective_link,
            )

    fields = build_pdd_upload_log_fields(
        config=cfg,
        title=title,
        merchant_code=merchant_code,
        product_id=product_id,
        product_link=effective_link,
        account_name=effective_account_name,
        publish_start=effective_publish_start,
        publish_end=effective_publish_end,
        verified_at=verified,
        created_at_raw=created_at_raw,
    )

    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_pdd_upload_table_id(cfg, api)
    if not table_id:
        msg = f"未找到飞书表「{pdd_cfg.table_name}」，请检查 bitable_app_token 与表名"
        logger.error("feishu pdd upload log failed: %s", msg)
        return {"failed": True, "reason": "table_not_found", "message": msg}
    _ensure_pdd_upload_table_fields(api, cfg, app_token, table_id)

    fields = map_fields_to_table_names(api, app_token, table_id, fields)

    dedupe_field = _pdd_upload_dedupe_field(cfg)
    dedupe_value = product_id
    if not dedupe_value:
        dedupe_field = str(pdd_cfg.field_names.merchant_code or "商品编码").strip()
        dedupe_value = merchant_code
    if dedupe_field:
        try:
            existing = search_records_by_field(
                api,
                app_token,
                table_id,
                field_name=dedupe_field,
                value=dedupe_value,
            )
        except FeishuAPIError as exc:
            if exc.code in _WRONG_TABLE_ID_CODES:
                table_id, resolve_method = resolve_pdd_upload_table_id(cfg, api, save_table_id=True)
                if not table_id:
                    raise
                existing = search_records_by_field(
                    api,
                    app_token,
                    table_id,
                    field_name=dedupe_field,
                    value=dedupe_value,
                )
            elif exc.code in _INVALID_FILTER_CODES:
                logger.warning(
                    "feishu pdd upload log dedupe skipped: invalid filter field=%s product_id=%s err=%s",
                    dedupe_field,
                    dedupe_value,
                    exc,
                )
                print(
                    f"[{account_id or '-'}] [{listing_label or merchant_code}] "
                    f"飞书去重查询跳过（字段「{dedupe_field}」与表不匹配），将直接写入",
                    flush=True,
                )
                existing = []
            else:
                raise
        if existing:
            record_id = str(existing[0].get("record_id") or "").strip()
            if record_id:
                try:
                    batch_update_records(
                        api,
                        app_token,
                        table_id,
                        [{"record_id": record_id, "fields": fields}],
                    )
                except FeishuAPIError as exc:
                    if exc.code in _WRONG_TABLE_ID_CODES:
                        table_id, resolve_method = resolve_pdd_upload_table_id(cfg, api, save_table_id=True)
                        if not table_id:
                            raise
                        batch_update_records(
                            api,
                            app_token,
                            table_id,
                            [{"record_id": record_id, "fields": fields}],
                        )
                    else:
                        raise
                logger.info(
                    "[%s] feishu pdd upload log updated duplicate product_id=%s record_id=%s table=%s(%s)",
                    account_id or "-",
                    product_id,
                    record_id,
                    table_id,
                    resolve_method,
                )
                return {
                    "updated": True,
                    "product_id": product_id,
                    "table_id": table_id,
                    "resolve_method": resolve_method,
                    "record_ids": [record_id],
                    "fields": fields,
                    "link_source": _link_source_label(
                        effective_link,
                        product_link_method,
                        used_fallback=used_link_fallback,
                    ),
                }
            logger.warning(
                "[%s] feishu pdd upload log duplicate without record_id product_id=%s",
                account_id or "-",
                product_id,
            )

    try:
        record_ids = batch_create_records(api, app_token, table_id, [fields])
    except FeishuAPIError as exc:
        if exc.code in _WRONG_TABLE_ID_CODES:
            table_id, resolve_method = resolve_pdd_upload_table_id(cfg, api, save_table_id=True)
            if not table_id:
                raise FeishuAPIError(
                    f"飞书表 ID 无效，且无法按表名「{pdd_cfg.table_name}」解析，请检查 config/feishu.yaml",
                    code=exc.code,
                    payload=exc.payload,
                ) from exc
            record_ids = batch_create_records(api, app_token, table_id, [fields])
        else:
            raise

    logger.info(
        "[%s] feishu pdd upload log created product_id=%s record_id=%s table=%s(%s)",
        account_id or "-",
        product_id,
        record_ids[0] if record_ids else "",
        table_id,
        resolve_method,
    )
    return {
        "created": True,
        "product_id": product_id,
        "table_id": table_id,
        "resolve_method": resolve_method,
        "record_ids": record_ids,
        "fields": fields,
        "link_source": _link_source_label(
            effective_link,
            product_link_method,
            used_fallback=used_link_fallback,
        ),
    }


def _format_push_failure(exc: Exception, **kwargs: Any) -> str:
    account_id = str(kwargs.get("account_id") or "-")
    label = str(kwargs.get("listing_label") or kwargs.get("merchant_code") or "-")
    product_id = str(kwargs.get("product_id") or "-")
    link = str(kwargs.get("product_link") or "(空)")
    method = str(kwargs.get("product_link_method") or "-")
    if isinstance(exc, FeishuAPIError):
        code = exc.code if exc.code is not None else "?"
        if exc.code in _WRONG_TABLE_ID_CODES:
            return (
                f"[{account_id}] [{label}] 飞书 PDD 上传日志失败：表 ID 无效(code={code})。"
                f"请到飞书多维表格页确认「PDD每日上传商品日志」的 table_id，"
                f"或检查 config/feishu.yaml 中 pdd_upload_log.table_name。"
                f" 本次抓取 product_id={product_id} link={link} link_method={method}"
            )
        if exc.code == 1254063:
            return (
                f"[{account_id}] [{label}] 飞书 PDD 上传日志失败：字段类型不匹配(MultiSelectFieldConvFail)。"
                f"请检查飞书表「状态/限时限量购状态」等列是否为多选，且选项名与 config/feishu.yaml 一致。"
                f" product_id={product_id}"
            )
        return (
            f"[{account_id}] [{label}] 飞书 PDD 上传日志失败：{exc} "
            f"(product_id={product_id} link={link} link_method={method})"
        )
    return (
        f"[{account_id}] [{label}] 飞书 PDD 上传日志失败：{exc} "
        f"(product_id={product_id} link={link} link_method={method})"
    )


def _push_pdd_upload_log_safe(**kwargs: Any) -> None:
    account_id = str(kwargs.get("account_id") or "")
    label = str(kwargs.get("listing_label") or kwargs.get("merchant_code") or "")
    try:
        result = push_pdd_upload_log(**kwargs)
        if result.get("created"):
            print(
                f"[{account_id}] [{label}] 飞书 PDD 上传日志已写入 "
                f"record_id={result.get('record_ids', [''])[0]} "
                f"table={result.get('table_id')} "
                f"link_source={result.get('link_source')}",
                flush=True,
            )
        elif result.get("updated"):
            print(
                f"[{account_id}] [{label}] 飞书 PDD 上传日志已更新（商品链接ID已存在） "
                f"record_id={result.get('record_ids', [''])[0]} "
                f"table={result.get('table_id')}",
                flush=True,
            )
        elif result.get("skipped"):
            print(
                f"[{account_id}] [{label}] 飞书 PDD 上传日志跳过：{result.get('reason')}",
                flush=True,
            )
        elif result.get("failed"):
            print(f"[{account_id}] [{label}] 飞书 PDD 上传日志失败：{result.get('message')}", flush=True)
    except Exception as exc:
        message = _format_push_failure(exc, **kwargs)
        logger.exception("feishu pdd upload log failed account=%s label=%s", account_id, label)
        print(message, flush=True)


def schedule_pdd_upload_log(**kwargs: Any) -> None:
    """写入 PDD 发布成功日志。默认上架路径同步写入，确保后续步骤能检索到记录。"""
    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.pdd_upload_log.enabled:
        return

    if cfg.pdd_upload_log.sync_on_listing:
        _push_pdd_upload_log_safe(**kwargs)
        return

    thread = threading.Thread(
        target=_push_pdd_upload_log_safe,
        kwargs=kwargs,
        name="feishu-pdd-upload-log",
        daemon=True,
    )
    thread.start()


def _push_pdd_upload_failure_log_safe(**kwargs: Any) -> None:
    account_id = str(kwargs.get("account_id") or "")
    label = str(kwargs.get("listing_label") or kwargs.get("merchant_code") or "")
    try:
        result = push_pdd_upload_failure_log(**kwargs)
        if result.get("created"):
            print(
                f"[{account_id}] [{label}] 飞书 PDD 发布失败日志已写入 "
                f"record_id={result.get('record_ids', [''])[0]} "
                f"table={result.get('table_id')}",
                flush=True,
            )
        elif result.get("skipped"):
            print(
                f"[{account_id}] [{label}] 飞书 PDD 发布失败日志跳过：{result.get('reason')}",
                flush=True,
            )
        elif result.get("failed"):
            print(
                f"[{account_id}] [{label}] 飞书 PDD 发布失败日志失败：{result.get('message')}",
                flush=True,
            )
    except Exception as exc:
        logger.exception("feishu pdd upload failure log failed account=%s label=%s", account_id, label)
        print(f"[{account_id}] [{label}] 飞书 PDD 发布失败日志失败：{exc}", flush=True)


def schedule_pdd_upload_failure_log(**kwargs: Any) -> None:
    """写入 PDD 发布失败/跳过日志（同步写入，确保每条失败都落表）。"""
    from pdd_agent.integrations.feishu.listing_feishu_platform_guard import PLATFORM_SKIP_REASON

    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.pdd_upload_log.failure_log_enabled:
        return

    failure_reason = str(kwargs.get("failure_reason") or "").strip()
    merchant_code = str(kwargs.get("merchant_code") or "").strip()
    report_platform = str(kwargs.get("report_platform") or "").strip() or "拼多多"
    if failure_reason == PLATFORM_SKIP_REASON and merchant_code:
        from pdd_agent.integrations.feishu.platform_skip_dedupe_cache import (
            is_platform_skip_merchant_code,
            remember_platform_skip_merchant_code,
        )

        if is_platform_skip_merchant_code(
            merchant_code,
            platform=report_platform,
            config=cfg,
            require_enabled=False,
        ):
            logger.info(
                "platform skip failure log deduped merchant_code=%s platform=%s",
                merchant_code,
                report_platform,
            )
            return

    account_id = str(kwargs.get("account_id") or "")
    label = str(kwargs.get("listing_label") or merchant_code or "")
    try:
        result = push_pdd_upload_failure_log(**kwargs)
        if result.get("created"):
            print(
                f"[{account_id}] [{label}] 飞书 PDD 发布失败日志已写入 "
                f"record_id={result.get('record_ids', [''])[0]} "
                f"table={result.get('table_id')}",
                flush=True,
            )
            if failure_reason == PLATFORM_SKIP_REASON and merchant_code:
                from pdd_agent.integrations.feishu.platform_skip_dedupe_cache import (
                    remember_platform_skip_merchant_code,
                )

                remember_platform_skip_merchant_code(merchant_code, platform=report_platform)
        elif result.get("skipped"):
            print(
                f"[{account_id}] [{label}] 飞书 PDD 发布失败日志跳过：{result.get('reason')}",
                flush=True,
            )
        elif result.get("failed"):
            print(
                f"[{account_id}] [{label}] 飞书 PDD 发布失败日志失败：{result.get('message')}",
                flush=True,
            )
    except Exception as exc:
        logger.exception("feishu pdd upload failure log failed account=%s label=%s", account_id, label)
        print(f"[{account_id}] [{label}] 飞书 PDD 发布失败日志失败：{exc}", flush=True)
