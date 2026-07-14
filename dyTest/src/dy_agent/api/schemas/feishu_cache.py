"""飞书缓存 API 模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FeishuClearCacheOut(BaseModel):
    success: bool = True
    cleared: list[str] = Field(default_factory=list, description="已清理的缓存项")
    errors: list[str] = Field(default_factory=list, description="清理失败项")
    message: str = ""
    worker_scope: str = Field(
        default="current_process_only",
        description="仅清理当前 API worker 进程；多 worker 需各进程各清一次或重启",
    )


class FeishuFailureLogSettingsOut(BaseModel):
    failure_log_enabled: bool = True
    failure_table_name: str = ""
    failure_table_id: str = ""


class FeishuFailureLogSettingsUpdateIn(BaseModel):
    failure_log_enabled: bool
