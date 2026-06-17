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
    limited_time_status: str = "限时限量购状态"
    activity_20981: str = "618报名"
    activity_21365: str = "21365限量七折"
    promotion_status: str = "推广状态"
    listing_result: str = "上传商品日志回写结果"
    listing_error_reason: str = "上传商品日志报错原因"
    listing_manual_fix_status: str = "上传异常人工修正状态"
    listing_reentry_status: str = "修正后重回上传链路"
    marketing_result: str = "营销工具日志回写结果"
    marketing_error_reason: str = "营销工具日志报错原因"
    traffic_result: str = "投流数据日志回写结果"
    traffic_error_reason: str = "投流数据日志报错原因"
    traffic_report_date: str = "投流数据日期"
    traffic_spend: str = "成交花费(元)"
    traffic_amount: str = "交易额(元)"
    traffic_roi: str = "实际投产比"
    traffic_total_cost: str = "总花费(元)"
    traffic_net_amount: str = "净交易额(元)"
    traffic_net_roi: str = "净实际投产比"
    traffic_net_orders: str = "净成交笔数"
    traffic_cost_per_order: str = "每笔净成交花费(元)"
    chain_phase: str = "当前链路阶段"


class PddMarketingLogFieldNames(BaseModel):
    """PDD营销日志表 列名（投流昨日数据专用）。"""

    date: str = "日期"
    account_id: str = "店铺"
    product_id: str = "商品ID"
    traffic_result: str = "投流数据日志回写结果"
    traffic_error_reason: str = "投流数据日志报错原因"
    traffic_spend: str = "成交花费(元)"
    traffic_amount: str = "交易额(元)"
    traffic_roi: str = "实际投产比"
    traffic_total_cost: str = "总花费(元)"
    traffic_net_amount: str = "净交易额(元)"
    traffic_net_roi: str = "净实际投产比"
    traffic_net_orders: str = "净成交笔数"
    traffic_cost_per_order: str = "每笔净成交花费(元)"


class PddMarketingLogConfig(BaseModel):
    enabled: bool = Field(default=True, description="是否启用 PDD 营销日志表")
    table_id: str = Field(default="", description="PDD营销日志表 table_id")
    table_name: str = Field(default="PDD营销日志表", description="投流数据写入的飞书表名")
    traffic_report_enabled: bool = Field(default=True, description="是否启用投流昨日数据定时抓取")
    traffic_report_schedule_hour: int = Field(default=0, ge=0, le=23)
    traffic_report_schedule_minute: int = Field(default=1, ge=0, le=59)
    traffic_report_account_ids: list[str] = Field(
        default_factory=lambda: ["store_A"],
        description="投流昨日数据定时抓取店铺（仅这些 account_id）",
    )
    lookup_retries: int = Field(default=3, ge=1, le=20)
    lookup_interval_seconds: float = Field(default=1.0, ge=0.5, le=30.0)
    traffic_result_options: list[str] = Field(default_factory=lambda: ["成功", "失败"])
    field_names: PddMarketingLogFieldNames = Field(default_factory=PddMarketingLogFieldNames)


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
    status_options: list[str] = Field(
        default_factory=lambda: ["已上架", "报错上架失败"],
        description="「状态」单选字段选项（须与飞书表一致）",
    )
    limited_time_status_options: list[str] = Field(
        default_factory=lambda: ["成功", "失败"],
        description="「限时限量购状态」单选字段选项（须与飞书表一致）",
    )
    update_limited_time_status: bool = Field(
        default=True,
        description="限时限量购完成后按商品ID回写飞书「限时限量购状态」",
    )
    limited_time_lookup_retries: int = Field(
        default=6,
        ge=1,
        le=20,
        description="按商品ID查飞书记录的重试次数（应对上架日志异步写入延迟）",
    )
    limited_time_lookup_interval_seconds: float = Field(
        default=5.0,
        ge=0.5,
        le=30.0,
        description="每次查飞书记录的间隔秒数",
    )
    activity_status_options: list[str] = Field(
        default_factory=lambda: ["成功", "失败"],
        description="活动报名状态单选字段选项（618报名 / 21365限量七折 等，须与飞书表一致）",
    )
    update_activity_register_status: bool = Field(
        default=True,
        description="活动报名完成后按商品ID回写飞书对应活动列（20981→618报名，21365→21365限量七折）",
    )
    activity_register_fields: dict[str, str] = Field(
        default_factory=lambda: {
            "20981": "618报名",
            "21365": "21365限量七折",
        },
        description="活动 ID → 飞书列名",
    )
    promotion_status_options: list[str] = Field(
        default_factory=lambda: ["成功", "失败"],
        description="「推广状态」单选字段选项（须与飞书表一致）",
    )
    listing_result_options: list[str] = Field(
        default_factory=lambda: ["成功", "失败"],
        description="「上传商品日志回写结果」单选字段选项（须与飞书表一致）",
    )
    marketing_result_options: list[str] = Field(
        default_factory=lambda: ["成功", "失败"],
        description="「营销工具日志回写结果」单选字段选项（须与飞书表一致）",
    )
    traffic_result_options: list[str] = Field(
        default_factory=lambda: ["成功", "失败"],
        description="「投流数据日志回写结果」单选字段选项（须与飞书表一致）",
    )
    listing_manual_fix_status_options: list[str] = Field(
        default_factory=lambda: ["待处理", "已修正", "无需处理"],
        description="「上传异常人工修正状态」单选字段选项（须与飞书表一致）",
    )
    listing_reentry_status_options: list[str] = Field(
        default_factory=lambda: ["待回流上传", "已回流上传", "无需回流"],
        description="「修正后重回上传链路」单选字段选项（须与飞书表一致）",
    )
    update_promotion_status: bool = Field(
        default=True,
        description="推广任务完成后按商品ID回写飞书「推广状态」",
    )
    traffic_report_enabled: bool = Field(
        default=True,
        description="是否启用投流昨日数据定时抓取并回写飞书",
    )
    traffic_report_schedule_hour: int = Field(
        default=19,
        ge=0,
        le=23,
        description="投流数据定时抓取小时（默认19点）",
    )
    traffic_report_schedule_minute: int = Field(
        default=0,
        ge=0,
        le=59,
        description="投流数据定时抓取分钟",
    )
    sync_on_listing: bool = Field(
        default=True,
        description="上架成功后立即同步写入飞书（非等链路全部完成）；False 时改为后台线程",
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
    pdd_marketing_log: PddMarketingLogConfig = Field(default_factory=PddMarketingLogConfig)


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
    pdd_marketing_log: PddMarketingLogConfig = Field(default_factory=PddMarketingLogConfig)


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

    pdd_marketing_log = yaml_cfg.pdd_marketing_log
    if "pdd_marketing_log" in raw and isinstance(raw.get("pdd_marketing_log"), dict):
        pdd_marketing_log = PddMarketingLogConfig.model_validate(raw["pdd_marketing_log"])

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
        pdd_marketing_log=pdd_marketing_log,
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


def save_pdd_marketing_table_id_to_config(table_id: str, path: Path | None = None) -> None:
    """解析到 PDD 营销日志表后，把 table_id 写回 feishu.yaml。"""
    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    data: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    marketing_raw = data.get("pdd_marketing_log")
    if not isinstance(marketing_raw, dict):
        marketing_raw = {}
    marketing_raw["table_id"] = table_id
    data["pdd_marketing_log"] = marketing_raw
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
