"""PDD每日上传商品日志 — 上架核验成功后异步写入飞书。"""

from __future__ import annotations

import threading
from datetime import date, datetime, time
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.bitable import (
    batch_create_records,
    find_table_id_by_name,
    map_fields_to_table_names,
    search_records_by_field,
)
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    load_feishu_config,
    save_pdd_upload_table_id_to_config,
)
from pdd_agent.skills.delist.time_utils import extract_created_at_from_text
from pdd_agent.skills.listing.goods_list_capture import is_plain_goods_template_link

logger = get_logger(__name__)

_WRONG_TABLE_ID_CODES = frozenset({1254004})
_INVALID_FILTER_CODES = frozenset({1254018})


def _ms_timestamp(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _date_to_ms(day: date) -> int:
    return _ms_timestamp(datetime.combine(day, time.min))


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
    link = str(product_link or "").strip() or "(空)"
    if len(link) > 72:
        link = f"{link[:69]}..."
    return (
        f"account={account_id or '-'} label={listing_label or merchant_code or '-'} "
        f"product_id={product_id or '-'} merchant_code={merchant_code or '-'} "
        f"title={title or '-'} status={list_status or '销售中'} "
        f"created_at={created_at_raw or '-'} verified_at={verified.strftime('%Y-%m-%d %H:%M:%S')} "
        f"link_source={_link_source_label(product_link, product_link_method, used_fallback=used_link_fallback)} "
        f"link={link}"
    )


def build_pdd_upload_log_fields(
    *,
    config: FeishuConfig,
    title: str,
    merchant_code: str,
    product_id: str,
    product_link: str,
    list_status: str,
    created_at_raw: str,
    verified_at: datetime,
) -> dict[str, Any]:
    names = config.pdd_upload_log.field_names
    created_at = _parse_created_at(created_at_raw) or verified_at
    link = str(product_link or "").strip()
    if link and product_id and is_plain_goods_template_link(link, product_id):
        link = ""

    fields: dict[str, Any] = {
        names.date: _date_to_ms(verified_at.date()),
        names.title: str(title or "").strip(),
        names.merchant_code: str(merchant_code or "").strip(),
        names.created_at: _ms_timestamp(created_at),
        names.status: str(list_status or "销售中").strip() or "销售中",
        names.product_id: str(product_id or "").strip(),
    }
    if link:
        fields[names.link] = {"link": link, "text": title or product_id or link}
    return fields


def resolve_pdd_upload_table_id(
    cfg: FeishuConfig,
    client: FeishuClient,
    *,
    save_table_id: bool = True,
) -> tuple[str, str]:
    """按表名优先解析 PDD 上传日志 table_id，返回 (table_id, method)。"""
    pdd_cfg = cfg.pdd_upload_log
    app_token = str(cfg.bitable_app_token or "").strip()
    configured = str(pdd_cfg.table_id or "").strip()
    table_name = str(pdd_cfg.table_name or "").strip()

    if table_name:
        found = find_table_id_by_name(client, app_token, table_name)
        if found:
            if configured and configured != found:
                logger.warning(
                    "pdd upload log table_id corrected by name: config=%s actual=%s name=%s",
                    configured,
                    found,
                    table_name,
                )
            if save_table_id and found != configured:
                try:
                    save_pdd_upload_table_id_to_config(found)
                except Exception as exc:
                    logger.warning("save pdd upload table_id failed: %s", exc)
            return found, "table_name"

    if configured:
        return configured, "config_table_id"
    return "", "missing"


def push_pdd_upload_log(
    *,
    account_id: str = "",
    listing_label: str = "",
    title: str,
    merchant_code: str,
    product_id: str,
    product_link: str = "",
    product_link_method: str = "",
    list_status: str = "",
    created_at_raw: str = "",
    verified_at: datetime | None = None,
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
    if not product_id:
        return {"skipped": True, "reason": "missing_product_id"}

    verified = verified_at or datetime.now()
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
        list_status=list_status,
        created_at_raw=created_at_raw,
        verified_at=verified,
    )

    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_pdd_upload_table_id(cfg, api)
    if not table_id:
        msg = f"未找到飞书表「{pdd_cfg.table_name}」，请检查 bitable_app_token 与表名"
        logger.error("feishu pdd upload log failed: %s", msg)
        return {"failed": True, "reason": "table_not_found", "message": msg}

    fields = map_fields_to_table_names(api, app_token, table_id, fields)

    dedupe_field = str(pdd_cfg.dedupe_field or "").strip()
    if dedupe_field:
        try:
            existing = search_records_by_field(
                api,
                app_token,
                table_id,
                field_name=dedupe_field,
                value=product_id,
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
                    value=product_id,
                )
            elif exc.code in _INVALID_FILTER_CODES:
                logger.warning(
                    "feishu pdd upload log dedupe skipped: invalid filter field=%s product_id=%s err=%s",
                    dedupe_field,
                    product_id,
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
            logger.info(
                "[%s] feishu pdd upload log skipped duplicate product_id=%s table=%s(%s)",
                account_id or "-",
                product_id,
                table_id,
                resolve_method,
            )
            return {
                "skipped": True,
                "reason": "duplicate",
                "product_id": product_id,
                "table_id": table_id,
                "resolve_method": resolve_method,
            }

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
    """后台线程异步写入，不阻塞浏览器上架流程。"""
    try:
        cfg = load_feishu_config()
    except Exception as exc:
        logger.warning("load feishu config failed: %s", exc)
        return
    if not cfg.pdd_upload_log.enabled:
        return

    thread = threading.Thread(
        target=_push_pdd_upload_log_safe,
        kwargs=kwargs,
        name="feishu-pdd-upload-log",
        daemon=True,
    )
    thread.start()
