"""飞书开放平台 / 多维表格（Bitable）集成。"""

from pdd_agent.integrations.feishu.client import FeishuClient
from pdd_agent.integrations.feishu.listing_log import (
    LISTING_LOG_TABLE_NAME,
    ensure_listing_log_table,
    sync_listing_log_for_date,
)

__all__ = [
    "FeishuClient",
    "LISTING_LOG_TABLE_NAME",
    "ensure_listing_log_table",
    "sync_listing_log_for_date",
]
