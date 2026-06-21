"""PDD发布日志表 — 成功/失败分表写入飞书。

流程：
1. 上架核验成功 → 写入「PDD发布日志表」（按商品ID去重）
2. 上架失败/跳过 → 写入「PDD发布日志表(失败)」（简短失败原因）
3. 限时限量购 / 活动报名 / 推广 → 按商品ID检索成功表记录后 update 对应列
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime
from datetime import time as dt_time
from typing import Any

from pdd_agent.core.logging import get_logger
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
_FEISHU_FAILURE_RECORD_FAIL = "失败"
_FEISHU_FAILURE_RECORD_SKIP = "跳过"

_SKIP_LISTING_REASON_CODES = frozenset(
    {
        "slot_alignment_failed",
        "preflight_no_skus",
        "preflight_no_carousel",
        "preflight_no_detail",
        "preflight_catalog",
        "catalog_parse_warning",
        "no_valid_units",
        "image_file_missing",
    }
)

# 提交后核验/页面操作类失败：即使 retryable 也记「失败」，不能记「跳过」
_FAIL_LISTING_REASON_CODES = frozenset(
    {
        "rejected_after_publish",
        "published_but_not_found_in_on_sale_or_rejected",
        "submit_uncertain",
        "submit_blocked",
        "submit_exception",
        "submit_button_missing",
        "preview_not_ready",
        "preview_missing",
        "validation_errors",
        "validation_incomplete",
        "validation_required",
        "platform_listing_code_not_filled",
        "platform_listing_code_verify_failed",
        "needs_manual_login_or_captcha",
        "browser_transient_error",
        "browser_manually_closed",
        "page_or_material_changed",
        "unexpected_error",
        "price_fill_partial",
        "price_fill_row_not_found",
        "price_fill_by_index_failed",
        "listed",
        "feishu_product_catalog_missing",
    }
)

# 飞书失败表专用文案：运营可读、一行说清（对齐淘宝发布日志表风格）
FEISHU_FAILURE_REASON_LABELS: dict[str, str] = {
    "preview_not_ready": "预览图还没全部上传完，暂不能提交",
    "preview_missing": "页面提示还有预览图没上传",
    "platform_listing_code_not_filled": "底部商品编码没填",
    "platform_listing_code_verify_failed": "底部商品编码与货号不一致",
    "validation_errors": "页面还有红色错误项没改完",
    "validation_incomplete": "页面提示信息未填完整",
    "validation_required": "页面还有必填项没填",
    "submit_blocked": "点击提交被页面拦住",
    "submit_uncertain": "提交结果不确定，请到拼多多后台核对",
    "submit_button_missing": "找不到「提交并上架」按钮",
    "submit_exception": "点击提交时出错",
    "listed": "已提交但未抓到商品 ID",
    "rejected_after_publish": "提交后在「已驳回」找到商品，平台已驳回",
    "published_but_not_found_in_on_sale_or_rejected": "提交后在在售/驳回列表没找到刚上的商品，请人工核对",
    "needs_manual_login_or_captcha": "需要人工处理验证码或重新登录",
    "page_or_material_changed": "页面或素材异常（分类/规格/上传相关）",
    "browser_transient_error": "浏览器超时或断连，可重试",
    "browser_manually_closed": "浏览器被手动关闭，任务中断",
    "unexpected_error": "运行异常，请查看操作记录",
    "preflight_no_skus": "Excel 与预览图对不上，没有可上架规格",
    "preflight_no_carousel": "缺少主图（需 1-5 编号图）",
    "preflight_no_detail": "缺少详情图（需 7-9 编号图）",
    "preflight_catalog": "商品目录或素材有问题",
    "image_file_missing": "图片文件不存在或打不开",
    "price_fill_partial": "价格表没填完整（库存/拼团价/单买价/编码）",
    "price_fill_row_not_found": "价格表找不到对应规格行",
    "price_fill_by_index_failed": "按行号填写价格表失败",
    "catalog_parse_warning": "素材目录解析有问题",
    "no_valid_units": "没有可上架的套图（素材或校验未通过）",
    "slot_alignment_failed": "兄弟款预览图张数不一致，请核对各款图数",
    "task_cancelled": "任务已被用户停止",
    "user_cancelled": "任务已被用户停止",
    "feishu_product_catalog_missing": "飞书拼多多所有商品没数据",
}


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
) -> str:
    """把机器报错转成飞书失败表的一行白话。"""
    raw = _strip_bracket_label_from_message(str(message or error or "").strip())
    raw = raw.split("\n")[0].strip()
    code = str(reason_code or "").strip()

    if "槽位对齐" in raw or code == "slot_alignment_failed":
        detail_match = re.search(r"[（(]([^）)]+)[）)]", raw)
        detail = str(detail_match.group(1) or "").strip() if detail_match else ""
        if detail and ("=" in detail or "张" in detail):
            return f"兄弟款预览图张数不一致（{detail}）"
        count_match = re.search(
            r"(\S+)\s*有\s*(\d+)\s*张图[，,]\s*主款\s*(\S+)\s*有\s*(\d+)\s*张",
            raw,
        )
        if count_match:
            style, count, ref, ref_count = count_match.groups()
            return f"{style} 预览图 {count} 张，主款 {ref} 为 {ref_count} 张，数量对不上"
        if any(token in raw for token in ("兄弟款", "规格数量", "预览图数量", "SKU 数")):
            return "兄弟款预览图张数不一致，请核对各款图数"
        return FEISHU_FAILURE_REASON_LABELS["slot_alignment_failed"]

    if "未找到 1-5 主图" in raw or "1-5 主图" in raw or raw == "主图为空":
        return FEISHU_FAILURE_REASON_LABELS["preflight_no_carousel"]
    if "未找到 7-9 详情图" in raw or "7-9 详情图" in raw or raw == "详情图为空":
        return FEISHU_FAILURE_REASON_LABELS["preflight_no_detail"]
    if "无任何数字命名图" in raw or "数字命名图" in raw:
        num_match = re.search(r"[（(]([^）)]+)[）)]", raw)
        suffix = f" ({num_match.group(1)})" if num_match else ""
        return f"缺少按数字命名的图片{suffix}"
    if "商品目录不存在" in raw or "无套图" in raw:
        return "找不到商品目录或套图文件夹"
    if "无有效 SKU" in raw or "未解析到任何有效 SKU" in raw:
        return FEISHU_FAILURE_REASON_LABELS["preflight_no_skus"]
    if "缺少预览图" in raw:
        preview_match = re.search(r"缺少预览图[:：]\s*(\S+/\S+)", raw)
        if preview_match:
            return f"缺少规格预览图（{preview_match.group(1)}）"
        return "缺少规格预览图"
    if "图片无法打开" in raw or "图片文件" in raw or "不存在" in raw and "图" in raw:
        return FEISHU_FAILURE_REASON_LABELS["image_file_missing"]
    if "验证码" in raw or "滑块" in raw:
        return FEISHU_FAILURE_REASON_LABELS["needs_manual_login_or_captcha"]
    if "用户停止" in raw or "任务已取消" in raw or "cancel" in raw.lower():
        return FEISHU_FAILURE_REASON_LABELS["task_cancelled"]
    if code == "rejected_after_publish" or ("已驳回" in raw and "槽位" not in raw):
        return FEISHU_FAILURE_REASON_LABELS["rejected_after_publish"]
    if code in {
        "published_but_not_found_in_on_sale_or_rejected",
        "submit_uncertain",
    } or any(token in raw for token in ("没找到刚上", "未在在售", "未匹配到本次", "没找到本次")):
        if code == "submit_uncertain" and "不确定" not in raw and "未确认" not in raw:
            return FEISHU_FAILURE_REASON_LABELS["submit_uncertain"]
        if code == "published_but_not_found_in_on_sale_or_rejected" or "没找到" in raw or "未匹配" in raw:
            return FEISHU_FAILURE_REASON_LABELS["published_but_not_found_in_on_sale_or_rejected"]
        return FEISHU_FAILURE_REASON_LABELS["submit_uncertain"]
    if "timeout" in raw.lower() or "超时" in raw or "timed out" in raw.lower():
        if "点击" in raw or "按钮" in raw:
            retry_match = re.search(r"(\d+)\s*次", raw)
            suffix = f"（{retry_match.group(1)} 次重试后）" if retry_match else ""
            return f"页面操作等待超时{suffix}"
        return FEISHU_FAILURE_REASON_LABELS["browser_transient_error"]
    if "点击" in raw and "失败" in raw:
        retry_match = re.search(r"(\d+)\s*次", raw)
        suffix = f"（{retry_match.group(1)} 次重试后）" if retry_match else ""
        action = raw.split("失败", 1)[0].strip(" ：:")
        if action.startswith("点击"):
            return f"{action}失败{suffix}"
        return f"{raw.split('失败')[0]}失败{suffix}".strip()

    label = FEISHU_FAILURE_REASON_LABELS.get(code, "")
    if label:
        if raw and raw not in label and not label.startswith(raw[:8]):
            # 原始信息已是白话时优先保留（如 preflight 自定义 message）
            if len(raw) <= 80 and not re.search(r"\b(traceback|exception|error code)\b", raw, re.I):
                if any(token in raw for token in ("跳过", "缺少", "找不到", "未", "没", "无法", "不一致")):
                    return raw
        return label

    if raw:
        cleaned = re.sub(r"^(error|failed|failure)\s*[:：]\s*", "", raw, flags=re.I).strip()
        if len(cleaned) > 120:
            cleaned = cleaned[:117] + "..."
        return cleaned or "上架失败"
    return code or "上架失败"


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
) -> str:
    """失败表用：淘宝同款一行说明 —— 「跳过/失败: 套图路径: 原因」。"""
    code = str(reason_code or "").strip()
    label = str(listing_label or "").strip()
    raw = str(message or error or "").strip()
    if raw and not label:
        parsed_label, _ = parse_listing_label_from_text(raw)
        if parsed_label:
            label = parsed_label

    body = _humanize_listing_failure_message(reason_code=code, message=message, error=error)
    record = str(record_type or "").strip()
    if record and label:
        return f"{record}: {label}: {body}"[:500]
    if label and label not in body:
        return f"{label}: {body}"[:200]
    return body[:200]


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
        first = parts[0]
        if re.match(r"^[A-Z0-9]{3,}[A-Z]?$", first, flags=re.IGNORECASE):
            return first
        return parts[-1]

    bracket = re.match(r"^\[([^\]]+)\]", raw)
    if bracket:
        label = bracket.group(1).strip()
        return label, _merchant_code_from_label(label)
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
        {"field_name": names.account_name, "type": FIELD_TEXT},
        {
            "field_name": names.record_type,
            "type": FIELD_SINGLE_SELECT,
            "property": {"options": [{"name": x} for x in pdd_cfg.failure_record_type_options]},
        },
        {"field_name": names.failure_reason, "type": FIELD_TEXT},
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
    if not pdd_cfg.enabled:
        return {"skipped": True, "reason": "pdd_upload_log_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    api = client or FeishuClient(cfg)
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
    record_type: str,
    failure_reason: str,
    publish_start: datetime | None = None,
    publish_end: datetime | None = None,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    names = config.pdd_upload_log.failure_field_names
    end_at = publish_end or datetime.now()
    start_at = publish_start or end_at
    duration = duration_seconds
    if duration is None:
        duration = max(0.0, (end_at - start_at).total_seconds())

    fields: dict[str, Any] = {
        names.date: _date_to_ms(end_at.date()),
        names.merchant_code: str(merchant_code or "").strip(),
        names.account_name: str(account_name or "").strip(),
        names.record_type: str(record_type or _FEISHU_FAILURE_RECORD_FAIL).strip(),
        names.failure_reason: str(failure_reason or "").strip()[:500],
        names.publish_start: _ms_timestamp(start_at),
        names.publish_end: _ms_timestamp(end_at),
        names.duration_seconds: round(float(duration), 2),
    }
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
    error: str = "",
    message: str = "",
    publish_start: datetime | None = None,
    publish_end: datetime | None = None,
    duration_seconds: float | None = None,
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

    code = str(merchant_code or "").strip()
    label = str(listing_label or "").strip()
    raw_msg = str(message or error or failure_reason or "").strip()
    if not code and not label and raw_msg:
        label, code = parse_listing_label_from_text(raw_msg)
    if not code and not label:
        code = str(account_id or "未知").strip() or "未知"

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
    )

    fields = build_pdd_upload_failure_log_fields(
        config=cfg,
        merchant_code=code or "",
        account_name=store_name,
        record_type=record_type_value,
        failure_reason=brief,
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


def _field_defs_for_pdd_upload_log(config: FeishuConfig) -> list[dict[str, Any]]:
    names = config.pdd_upload_log.field_names
    datetime_prop = {"date_formatter": "yyyy/MM/dd HH:mm", "auto_fill": False}
    return [
        {"field_name": names.date, "type": FIELD_DATETIME, "property": {"date_formatter": "yyyy/MM/dd", "auto_fill": False}},
        {"field_name": names.merchant_code, "type": FIELD_TEXT},
        {"field_name": names.title, "type": FIELD_TEXT},
        {"field_name": names.account_name, "type": FIELD_TEXT},
        {"field_name": names.product_id, "type": FIELD_TEXT},
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

    dedupe_field = str(pdd_cfg.dedupe_field or pdd_cfg.field_names.product_id or "商品ID").strip()
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

    dedupe_field = str(pdd_cfg.dedupe_field or pdd_cfg.field_names.product_id or "商品ID").strip()
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
    """按商品ID更新飞书「限时限量购状态」单选字段。"""
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
    """按商品ID更新飞书活动报名列（20981→618报名，21365→21365限量七折）。"""
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
    """按商品ID更新飞书「推广状态」单选字段。"""
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
                    f"未找到记录的商品ID：{', '.join(missing)}",
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
    try:
        from pdd_agent.core.config import load_yaml_settings
        from pdd_agent.db.repositories import get_account_config

        settings = load_yaml_settings()
        account = get_account_config(settings, str(account_id or "").strip())
        if account and str(account.username or "").strip():
            return str(account.username).strip()
    except Exception:
        pass
    return str(account_id or "").strip()


def build_pdd_upload_log_fields(
    *,
    config: FeishuConfig,
    title: str,
    merchant_code: str,
    product_id: str,
    product_link: str,
    account_name: str = "",
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
        names.product_id: str(product_id or "").strip(),
        names.publish_start: _ms_timestamp(start_at),
        names.publish_end: _ms_timestamp(end_at),
        names.duration_seconds: round(duration, 2),
    }
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

    dedupe_field = str(pdd_cfg.dedupe_field or "").strip()
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
                f"[{account_id}] [{label}] 飞书 PDD 上传日志已更新（商品ID已存在） "
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
    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.pdd_upload_log.enabled:
        return

    _push_pdd_upload_failure_log_safe(**kwargs)
