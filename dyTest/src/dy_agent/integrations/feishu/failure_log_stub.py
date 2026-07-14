"""抖店暂不写 PDD 发布失败日志表；保留接口避免商品表缺项同步报错。"""

from __future__ import annotations

from dy_agent.core.logging import get_logger

logger = get_logger(__name__)


def schedule_pdd_upload_failure_log(**kwargs) -> None:
    logger.debug(
        "skip feishu failure log on dy: merchant_code=%s reason=%s",
        kwargs.get("merchant_code"),
        kwargs.get("reason_code"),
    )
