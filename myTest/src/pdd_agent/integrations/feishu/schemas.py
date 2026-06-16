"""飞书测试 API 请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FeishuConfigOut(BaseModel):
    config_path: str
    app_id: str
    app_secret_masked: str
    oauth_redirect_uri: str
    oauth_scope: str
    use_user_access_token: bool
    user_token_ready: bool
    bitable_app_token: str
    table_id: str
    table_name: str
    dedupe_field: str
    field_names: dict[str, str]


class FeishuCheckResult(BaseModel):
    ok: bool
    message: str
    token_length: int = 0
    auth_mode: str = "user_access_token"


class FeishuOAuthAuthorizeResult(BaseModel):
    authorize_url: str
    state: str
    scope: str
    redirect_uri: str


class FeishuOAuthExchangeRequest(BaseModel):
    code: str = Field(description="授权回调中的 code")
    state: str = ""
    redirect_uri: str = ""


class FeishuOAuthExchangeResult(BaseModel):
    ok: bool
    message: str
    access_token_length: int = 0
    expires_in: int = 0
    refresh_token_present: bool = False


class FeishuInitTableResult(BaseModel):
    table_name: str
    table_id: str
    message: str


class FeishuSyncRequest(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    dry_run: bool = False
    minimal_fields: bool = Field(
        default=True,
        description="仅写入标准 8 列（日期/链接/标签/价格等），适配已有表结构",
    )


class FeishuPreviewItem(BaseModel):
    mapping_id: str
    account_id: str
    product_code: str
    listing_label: str
    pdd_product_id: str
    published_at: str


class FeishuPreviewResult(BaseModel):
    date: str
    count: int
    items: list[FeishuPreviewItem]
