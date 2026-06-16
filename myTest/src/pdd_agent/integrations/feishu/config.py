"""飞书集成配置（独立 YAML，不写入 settings.yaml）。"""

from __future__ import annotations

import os
import time
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from pdd_agent.paths import CONFIG_DIR, PROJECT_ROOT

DEFAULT_FEISHU_CONFIG_PATH = CONFIG_DIR / "feishu.yaml"


class FeishuEnvSettings(BaseSettings):
    """可从 .env 覆盖的敏感项。"""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_bitable_app_token: str = ""


class FeishuFieldNames(BaseModel):
    """飞书表列名（与「技术支持」Base 中表头一致时可只改 title）。"""

    date: str = "日期"
    link: str = "商品链接"
    title: str = "宝贝标签"
    price: str = "一口价"
    merchant_code: str = "商家编码"
    sku_count: str = "规格数"
    published_at: str = "发布时间"
    status: str = "状态"
    mapping_id: str = "映射ID"
    account_id: str = "店铺"
    pdd_product_id: str = "拼多多商品ID"
    product_code: str = "商品编码"
    image_set: str = "套图"


class PddUploadLogFieldNames(BaseModel):
    """PDD每日上传商品日志 表列名。"""

    date: str = "日期"
    link: str = "商品链接"
    title: str = "宝贝标题"
    merchant_code: str = "商品编码"
    created_at: str = "创建时间"
    status: str = "状态"
    product_id: str = "商品ID"


class PddUploadLogConfig(BaseModel):
    enabled: bool = Field(
        default=False,
        description="上架核验成功后是否异步写入 PDD 上传日志表",
    )
    table_id: str = Field(
        default="",
        description="PDD每日上传商品日志 table_id",
    )
    table_name: str = Field(
        default="PDD每日上传商品日志",
        description="表名（仅文档用途，写入时用 table_id）",
    )
    dedupe_field: str = Field(
        default="商品ID",
        description="幂等去重字段名",
    )
    field_names: PddUploadLogFieldNames = Field(default_factory=PddUploadLogFieldNames)


class FeishuYamlConfig(BaseModel):
    """config/feishu.yaml 结构。"""

    app_id: str = ""
    app_secret: str = ""
    oauth_redirect_uri: str = Field(
        default="http://127.0.0.1:5174/oauth/callback",
        description="飞书 OAuth 回调地址（需在开放平台安全设置中配置）",
    )
    oauth_scope: str = Field(
        default="offline_access bitable:app",
        description="授权页 scope，空格分隔",
    )
    use_user_access_token: bool = Field(
        default=True,
        description="是否优先使用 user_access_token 调用 API",
    )
    user_access_token: str = ""
    user_access_token_expires_at: int = 0
    refresh_token: str = ""
    refresh_token_expires_at: int = 0
    bitable_app_token: str = Field(
        default="",
        description="多维表格 Base 的 app_token（浏览器地址 /base/ 后那段）",
    )
    table_id: str = Field(
        default="",
        description="已建好的数据表 table_id（URL 中 table= 后那段）；留空则 init 时自动创建",
    )
    table_name: str = Field(
        default="拼多多每日上架商品日志",
        description="init-table 时新建的数据表名称",
    )
    field_names: FeishuFieldNames = Field(default_factory=FeishuFieldNames)
    product_link_template: str = Field(
        default="https://mobile.yangkeduo.com/goods.html?goods_id={pdd_product_id}",
        description="拼多多 C 端商品链接模板",
    )
    merchant_goods_url_template: str = Field(
        default="https://mms.pinduoduo.com/goods/goods_detail?goods_id={pdd_product_id}",
        description="商家后台商品详情链接（写入飞书「商品链接」）",
    )
    dedupe_field: str = Field(
        default="映射ID",
        description="用于幂等去重的字段名（mapping_id）",
    )
    status_options: list[str] = Field(
        default_factory=lambda: ["在售", "已下架", "未知"],
        description="「状态」单选字段选项",
    )
    pdd_upload_log: PddUploadLogConfig = Field(default_factory=PddUploadLogConfig)


class FeishuConfig(BaseModel):
    app_id: str
    app_secret: str
    oauth_redirect_uri: str = "http://127.0.0.1:5174/oauth/callback"
    oauth_scope: str = "offline_access bitable:app"
    use_user_access_token: bool = True
    user_access_token: str = ""
    user_access_token_expires_at: int = 0
    refresh_token: str = ""
    refresh_token_expires_at: int = 0
    bitable_app_token: str
    table_id: str = ""
    table_name: str = "拼多多每日上架商品日志"
    field_names: FeishuFieldNames = Field(default_factory=FeishuFieldNames)
    product_link_template: str = "https://mobile.yangkeduo.com/goods.html?goods_id={pdd_product_id}"
    merchant_goods_url_template: str = (
        "https://mms.pinduoduo.com/goods/goods_detail?goods_id={pdd_product_id}"
    )
    dedupe_field: str = "映射ID"
    status_options: list[str] = Field(default_factory=lambda: ["在售", "已下架", "未知"])
    pdd_upload_log: PddUploadLogConfig = Field(default_factory=PddUploadLogConfig)


def load_feishu_config(path: Path | None = None) -> FeishuConfig:
    """合并 feishu.yaml 与 .env 中的飞书凭据。"""
    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    raw: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    yaml_cfg = FeishuYamlConfig.model_validate(raw)
    env = get_feishu_env_settings()

    field_names = yaml_cfg.field_names
    if "dedupe_field" in raw:
        dedupe_field = str(raw.get("dedupe_field") or "")
    else:
        dedupe_field = field_names.mapping_id

    pdd_upload_log = yaml_cfg.pdd_upload_log
    if "pdd_upload_log" in raw and isinstance(raw.get("pdd_upload_log"), dict):
        pdd_upload_log = PddUploadLogConfig.model_validate(raw["pdd_upload_log"])

    return FeishuConfig(
        app_id=env.feishu_app_id or yaml_cfg.app_id,
        app_secret=env.feishu_app_secret or yaml_cfg.app_secret,
        oauth_redirect_uri=yaml_cfg.oauth_redirect_uri,
        oauth_scope=yaml_cfg.oauth_scope,
        use_user_access_token=bool(yaml_cfg.use_user_access_token),
        user_access_token=str(yaml_cfg.user_access_token or ""),
        user_access_token_expires_at=int(yaml_cfg.user_access_token_expires_at or 0),
        refresh_token=str(yaml_cfg.refresh_token or ""),
        refresh_token_expires_at=int(yaml_cfg.refresh_token_expires_at or 0),
        bitable_app_token=env.feishu_bitable_app_token or yaml_cfg.bitable_app_token,
        table_id=yaml_cfg.table_id,
        table_name=yaml_cfg.table_name,
        field_names=field_names,
        product_link_template=yaml_cfg.product_link_template,
        merchant_goods_url_template=yaml_cfg.merchant_goods_url_template,
        dedupe_field=dedupe_field,
        status_options=list(yaml_cfg.status_options),
        pdd_upload_log=pdd_upload_log,
    )


@lru_cache
def get_feishu_env_settings() -> FeishuEnvSettings:
    return FeishuEnvSettings()


def save_table_id_to_config(table_id: str, path: Path | None = None) -> None:
    """init-table 成功后把 table_id 写回 feishu.yaml。"""
    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    data: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    data["table_id"] = table_id
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def save_pdd_upload_table_id_to_config(table_id: str, path: Path | None = None) -> None:
    """解析到 PDD 上传日志表后，把 table_id 写回 feishu.yaml。"""
    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    data: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    pdd_raw = data.get("pdd_upload_log")
    if not isinstance(pdd_raw, dict):
        pdd_raw = {}
    pdd_raw["table_id"] = table_id
    data["pdd_upload_log"] = pdd_raw
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def save_oauth_tokens_to_config(
    *,
    user_access_token: str,
    expires_in: int,
    refresh_token: str = "",
    refresh_token_expires_in: int = 0,
    path: Path | None = None,
) -> None:
    """OAuth 成功后把 user_access_token / refresh_token 写回 feishu.yaml。"""
    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    data: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    now = int(time.time())
    data["user_access_token"] = user_access_token
    data["user_access_token_expires_at"] = now + int(expires_in or 0)
    data["refresh_token"] = refresh_token
    data["refresh_token_expires_at"] = now + int(refresh_token_expires_in or 0)

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
