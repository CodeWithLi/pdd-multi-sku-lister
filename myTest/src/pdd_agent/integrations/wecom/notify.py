"""业务场景的企业微信通知。"""

from __future__ import annotations

from pdd_agent.integrations.wecom.client import send_if_enabled
from pdd_agent.integrations.wecom.config import load_wecom_config


def notify_listing_failed(
    *,
    account_id: str,
    listing_label: str,
    reason: str,
) -> None:
    cfg = load_wecom_config()
    if not cfg.notify_on_listing_failed:
        return
    content = (
        "【上架失败】\n"
        f"店铺：{account_id or '—'}\n"
        f"单元：{listing_label or '—'}\n"
        f"原因：{(reason or '—')[:1500]}"
    )
    send_if_enabled(content, cfg=cfg)


def notify_pipeline_failed(
    *,
    account_id: str,
    pipeline_id: str,
    product_codes: list[str],
    error: str,
    current_step: str = "",
) -> None:
    cfg = load_wecom_config()
    if not cfg.notify_on_pipeline_failed:
        return
    codes = ", ".join(str(c) for c in product_codes if str(c).strip()) or "—"
    content = (
        "【整合链路失败】\n"
        f"链路：{pipeline_id or '—'}\n"
        f"店铺：{account_id or '—'}\n"
        f"步骤：{current_step or '—'}\n"
        f"商品：{codes}\n"
        f"原因：{(error or '—')[:1200]}"
    )
    send_if_enabled(content, cfg=cfg)
