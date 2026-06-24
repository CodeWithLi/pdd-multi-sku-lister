"""失败日志循环上架占用：Redis 互斥 + 飞书「是否循环上架」占位。

飞书多维表格每行有 API 级 ``record_id``（如 ``recXXXXXXXX``），UI 默认不展示，
可通过本系统「原始数据」或飞书开放平台调试看到。占用与去重均以 ``record_id`` 为准。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.bitable import batch_update_records, map_fields_to_table_names, list_fields
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    PddFailureCycleRelistWatchConfig,
    load_feishu_config,
)
from pdd_agent.integrations.feishu.field_display import encode_cycle_relist_write_value
from pdd_agent.integrations.feishu.pdd_failure_log_read import (
    resolve_cycle_relist_field_name,
    resolve_failure_log_table,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class CycleRelistClaimResult:
    ok: bool
    claimed: bool
    record_id: str
    reason: str = ""
    error: str = ""
    redis_claimed: bool = False
    feishu_updated: bool = False
    placeholder: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "claimed": self.claimed,
            "record_id": self.record_id,
            "reason": self.reason,
            "error": self.error,
            "redis_claimed": self.redis_claimed,
            "feishu_updated": self.feishu_updated,
            "placeholder": self.placeholder,
        }


def _redis_key(record_id: str) -> str:
    from pdd_agent.integrations.redis.config import load_redis_config

    prefix = str(load_redis_config().key_prefix or "pdd").strip() or "pdd"
    return f"{prefix}:failure_cycle_relist:claim:{record_id}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _claim_payload(
    *,
    record_id: str,
    merchant_code: str = "",
    account_name: str = "",
    placeholder: str = "",
) -> str:
    return json.dumps(
        {
            "record_id": record_id,
            "merchant_code": merchant_code,
            "account_name": account_name,
            "placeholder": placeholder,
            "claimed_at": _utc_now_iso(),
        },
        ensure_ascii=False,
    )


def get_cycle_relist_claim(record_id: str) -> dict[str, Any] | None:
    """读取 Redis 占用信息；无占用或 Redis 不可用时返回 None。"""
    rid = str(record_id or "").strip()
    if not rid:
        return None
    try:
        from pdd_agent.integrations.redis.client import get_redis_client

        client = get_redis_client()
        if client is None:
            return None
        raw = client.get(_redis_key(rid))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(str(raw))
    except Exception:
        logger.exception("read cycle relist claim failed record_id=%s", rid)
        return None


def _redis_try_claim(
    record_id: str,
    *,
    merchant_code: str,
    account_name: str,
    placeholder: str,
    ttl_seconds: int,
) -> tuple[bool, bool]:
    """返回 (redis_available, acquired)。"""
    try:
        from pdd_agent.integrations.redis.client import get_redis_client

        client = get_redis_client()
        if client is None:
            return False, False
        acquired = bool(
            client.set(
                _redis_key(record_id),
                _claim_payload(
                    record_id=record_id,
                    merchant_code=merchant_code,
                    account_name=account_name,
                    placeholder=placeholder,
                ),
                nx=True,
                ex=max(60, int(ttl_seconds)),
            )
        )
        return True, acquired
    except Exception:
        logger.exception("redis claim failed record_id=%s", record_id)
        return False, False


def _redis_release(record_id: str) -> bool:
    try:
        from pdd_agent.integrations.redis.client import get_redis_client

        client = get_redis_client()
        if client is None:
            return False
        client.delete(_redis_key(record_id))
        return True
    except Exception:
        logger.exception("redis release failed record_id=%s", record_id)
        return False


def _write_feishu_cycle_relist(
    *,
    config: FeishuConfig,
    client: FeishuClient,
    record_id: str,
    value: str | None,
) -> tuple[bool, str]:
    app_token = str(config.bitable_app_token or "").strip()
    if not app_token:
        return False, "未配置 bitable_app_token"

    table_id, _, method = resolve_failure_log_table(config, client)
    if not table_id:
        return False, f"未找到失败日志表（resolve={method}）"

    table_fields = list_fields(client, app_token, table_id)
    configured = str(config.pdd_upload_log.failure_field_names.cycle_relist or "是否已循环上架")
    field_name = resolve_cycle_relist_field_name(configured, table_fields)
    field_meta = next(
        (item for item in table_fields if str(item.get("field_name") or "") == field_name),
        {},
    )

    encoded = encode_cycle_relist_write_value(value, field_meta)
    raw_fields: dict[str, Any] = {field_name: encoded}
    mapped_fields = map_fields_to_table_names(client, app_token, table_id, raw_fields)

    try:
        batch_update_records(
            client,
            app_token,
            table_id,
            [{"record_id": record_id, "fields": mapped_fields}],
        )
    except FeishuAPIError as exc:
        return False, str(exc)
    return True, ""


def try_claim_cycle_relist(
    record_id: str,
    *,
    merchant_code: str = "",
    account_name: str = "",
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    watch: PddFailureCycleRelistWatchConfig | None = None,
) -> CycleRelistClaimResult:
    """抢占循环上架：Redis NX + 飞书写入占位文案。

    顺序：Redis 抢占成功（或 Redis 不可用则跳过）→ 写飞书 → 飞书失败则回滚 Redis。
    """
    rid = str(record_id or "").strip()
    if not rid:
        return CycleRelistClaimResult(
            ok=False,
            claimed=False,
            record_id="",
            error="record_id 为空",
        )

    cfg = config or load_feishu_config()
    watch_cfg = watch or cfg.pdd_upload_log.failure_cycle_relist_watch
    placeholder = str(watch_cfg.claim_placeholder or "循环上架中").strip() or "循环上架中"
    ttl = int(watch_cfg.claim_redis_ttl_seconds or 7200)

    existing = get_cycle_relist_claim(rid)
    if existing:
        return CycleRelistClaimResult(
            ok=True,
            claimed=False,
            record_id=rid,
            reason="redis_locked",
            placeholder=str(existing.get("placeholder") or placeholder),
        )

    redis_available, redis_acquired = _redis_try_claim(
        rid,
        merchant_code=merchant_code,
        account_name=account_name,
        placeholder=placeholder,
        ttl_seconds=ttl,
    )
    if redis_available and not redis_acquired:
        return CycleRelistClaimResult(
            ok=True,
            claimed=False,
            record_id=rid,
            reason="redis_locked",
            placeholder=placeholder,
        )

    api = client or FeishuClient(cfg)
    feishu_ok, feishu_err = _write_feishu_cycle_relist(
        config=cfg,
        client=api,
        record_id=rid,
        value=placeholder,
    )
    if not feishu_ok:
        if redis_acquired:
            _redis_release(rid)
        return CycleRelistClaimResult(
            ok=False,
            claimed=False,
            record_id=rid,
            error=feishu_err or "飞书写入失败",
            redis_claimed=False,
            feishu_updated=False,
            placeholder=placeholder,
        )

    logger.info(
        "cycle relist claimed record_id=%s merchant_code=%s placeholder=%s redis=%s",
        rid,
        merchant_code,
        placeholder,
        redis_acquired,
    )
    return CycleRelistClaimResult(
        ok=True,
        claimed=True,
        record_id=rid,
        reason="claimed",
        redis_claimed=redis_acquired,
        feishu_updated=True,
        placeholder=placeholder,
    )


def release_cycle_relist_claim(
    record_id: str,
    *,
    final_value: str | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    watch: PddFailureCycleRelistWatchConfig | None = None,
    update_feishu: bool = True,
) -> CycleRelistClaimResult:
    """释放占用：删 Redis；可选把飞书「是否循环上架」改为终态文案。"""
    rid = str(record_id or "").strip()
    if not rid:
        return CycleRelistClaimResult(
            ok=False,
            claimed=False,
            record_id="",
            error="record_id 为空",
        )

    cfg = config or load_feishu_config()
    watch_cfg = watch or cfg.pdd_upload_log.failure_cycle_relist_watch
    final = (
        str(final_value).strip()
        if final_value is not None
        else str(watch_cfg.claim_completed_value or "是").strip()
    )

    _redis_release(rid)

    feishu_updated = False
    if update_feishu and final:
        api = client or FeishuClient(cfg)
        feishu_updated, feishu_err = _write_feishu_cycle_relist(
            config=cfg,
            client=api,
            record_id=rid,
            value=final,
        )
        if not feishu_updated:
            return CycleRelistClaimResult(
                ok=False,
                claimed=False,
                record_id=rid,
                error=feishu_err or "飞书更新失败",
                feishu_updated=False,
                placeholder=final,
            )

    return CycleRelistClaimResult(
        ok=True,
        claimed=False,
        record_id=rid,
        reason="released",
        feishu_updated=feishu_updated,
        placeholder=final,
    )
