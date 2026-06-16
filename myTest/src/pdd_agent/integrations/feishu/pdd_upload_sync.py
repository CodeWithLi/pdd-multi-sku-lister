"""PDD每日上传商品日志 — 上架核验成功后异步写入飞书。"""

from __future__ import annotations

import threading
from datetime import date, datetime, time
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.bitable import batch_create_records, search_records_by_field
from pdd_agent.integrations.feishu.client import FeishuClient
from pdd_agent.integrations.feishu.config import FeishuConfig, load_feishu_config
from pdd_agent.skills.delist.time_utils import extract_created_at_from_text

logger = get_logger(__name__)


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
    if not link and product_id:
        link = config.product_link_template.format(pdd_product_id=product_id)

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


def push_pdd_upload_log(
    *,
    account_id: str = "",
    title: str,
    merchant_code: str,
    product_id: str,
    product_link: str = "",
    list_status: str = "",
    created_at_raw: str = "",
    verified_at: datetime | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    pdd_cfg = cfg.pdd_upload_log
    if not pdd_cfg.enabled:
        return {"skipped": True, "reason": "pdd_upload_log_disabled"}

    table_id = str(pdd_cfg.table_id or "").strip()
    app_token = str(cfg.bitable_app_token or "").strip()
    if not table_id or not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    product_id = str(product_id or "").strip()
    if not product_id:
        return {"skipped": True, "reason": "missing_product_id"}

    verified = verified_at or datetime.now()
    fields = build_pdd_upload_log_fields(
        config=cfg,
        title=title,
        merchant_code=merchant_code,
        product_id=product_id,
        product_link=product_link,
        list_status=list_status,
        created_at_raw=created_at_raw,
        verified_at=verified,
    )

    api = client or FeishuClient(cfg)
    dedupe_field = str(pdd_cfg.dedupe_field or "").strip()
    if dedupe_field:
        existing = search_records_by_field(
            api,
            app_token,
            table_id,
            field_name=dedupe_field,
            value=product_id,
        )
        if existing:
            logger.info(
                "[%s] feishu pdd upload log skipped duplicate product_id=%s",
                account_id or "-",
                product_id,
            )
            return {
                "skipped": True,
                "reason": "duplicate",
                "product_id": product_id,
                "table_id": table_id,
            }

    record_ids = batch_create_records(api, app_token, table_id, [fields])
    logger.info(
        "[%s] feishu pdd upload log created product_id=%s record_id=%s table=%s",
        account_id or "-",
        product_id,
        record_ids[0] if record_ids else "",
        table_id,
    )
    return {
        "created": True,
        "product_id": product_id,
        "table_id": table_id,
        "record_ids": record_ids,
        "fields": fields,
    }


def _push_pdd_upload_log_safe(**kwargs: Any) -> None:
    account_id = str(kwargs.get("account_id") or "")
    label = str(kwargs.get("listing_label") or kwargs.get("merchant_code") or "")
    try:
        result = push_pdd_upload_log(**kwargs)
        if result.get("created"):
            print(
                f"[{account_id}] [{label}] 飞书 PDD 上传日志已写入 record_id={result.get('record_ids', [''])[0]}",
                flush=True,
            )
        elif result.get("skipped"):
            print(
                f"[{account_id}] [{label}] 飞书 PDD 上传日志跳过：{result.get('reason')}",
                flush=True,
            )
    except Exception as exc:
        logger.exception("feishu pdd upload log failed account=%s label=%s", account_id, label)
        print(f"[{account_id}] [{label}] 飞书 PDD 上传日志失败：{exc}", flush=True)


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
