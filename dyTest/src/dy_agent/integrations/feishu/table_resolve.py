"""飞书多维表格 table_id 解析（与 PDD 共用表名/配置，不依赖 pdd_upload_sync）。"""

from __future__ import annotations

from typing import Any

from dy_agent.core.logging import get_logger
from dy_agent.integrations.feishu.bitable import create_table, find_table_id_by_name, list_fields
from dy_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from dy_agent.integrations.feishu.config import FeishuConfig

logger = get_logger(__name__)

_WRONG_TABLE_ID_CODES = frozenset({1254004, 1254041})


def verify_feishu_table_id(client: FeishuClient, app_token: str, table_id: str) -> bool:
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


def resolve_feishu_table_id(
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
        if found and verify_feishu_table_id(client, app_token, found):
            if configured and configured != found:
                logger.warning(
                    "feishu table_id corrected by name: config=%s actual=%s name=%s",
                    configured,
                    found,
                    name,
                )
            if save_table_id and found != configured:
                try:
                    save_fn(found)
                except Exception as exc:
                    logger.warning("save feishu table_id failed name=%s: %s", name, exc)
            return found, "table_name"
        if found and not verify_feishu_table_id(client, app_token, found):
            logger.warning(
                "feishu table name=%s maps to invalid table_id=%s, will recreate if allowed",
                name,
                found,
            )

    if configured and verify_feishu_table_id(client, app_token, configured):
        return configured, "config_table_id"
    if configured:
        logger.warning(
            "feishu configured table_id invalid: id=%s name=%s create_if_missing=%s",
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
                logger.warning("save feishu table_id failed after create name=%s: %s", name, exc)
        logger.info("feishu table created name=%s table_id=%s", name, created)
        return created, "created"

    return "", "missing"
