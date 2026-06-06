"""配置相关 API 模型。"""

import re

from pydantic import BaseModel, Field, field_validator

_ACCOUNT_ID_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


class AccountOut(BaseModel):
    """列表展示（不含密码明文）。"""

    account_id: str
    enabled: bool
    username: str = ""
    has_password: bool = False
    product_codes: list[str] = Field(default_factory=list)


class AccountDetailOut(AccountOut):
    """编辑用详情（本地控制台，含密码）。"""

    password: str = ""


class AccountCreateIn(BaseModel):
    account_id: str = Field(..., min_length=1, max_length=64)
    enabled: bool = True
    username: str = ""
    password: str = ""
    product_codes: list[str] = Field(default_factory=list)

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, v: str) -> str:
        v = v.strip()
        if not _ACCOUNT_ID_PATTERN.match(v):
            raise ValueError("店铺 ID 须以字母开头，仅含字母、数字、下划线")
        return v


class AccountUpdateIn(BaseModel):
    enabled: bool = True
    username: str = ""
    password: str = ""  # 留空表示不修改密码
    product_codes: list[str] = Field(default_factory=list)


class ConfigSummaryOut(BaseModel):
    """系统配置摘要。"""

    app_name: str
    log_level: str
    assets_root: str
    excel_path: str
    llm_configured: bool
    account_count: int
    enabled_account_count: int
