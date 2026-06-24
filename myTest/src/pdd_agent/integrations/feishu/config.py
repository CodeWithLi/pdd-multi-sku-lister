"""飞书集成配置（独立 YAML，不写入 settings.yaml）。"""

from __future__ import annotations

import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from pdd_agent.integrations.feishu.traffic_metric_columns import DEFAULT_TRAFFIC_METRIC_COLUMNS
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


class PddUploadFailureLogFieldNames(BaseModel):
    """淘宝+拼多多发布日志表（失败）列名。"""

    date: str = "日期"
    merchant_code: str = "商品编码"
    report_platform: str = "报错平台"
    account_name: str = "店铺名称"
    record_type: str = "记录类型"
    failure_reason: str = "失败原因"
    publish_start: str = "发布开始时间"
    publish_end: str = "发布结束时间"
    duration_seconds: str = "耗时秒"
    process_completed: str = "是否处理完成"
    process_status_mirror: str = "处理状态镜像"
    cycle_relist: str = "是否循环上架"
    processor: str = "人员"
    processed_at: str = "处理时间"


class PddUploadLogFieldNames(BaseModel):
    """PDD发布日志表 — 与淘宝发布日志表列一致（仅发布）。"""

    date: str = "日期"
    merchant_code: str = "商品编码"
    combo_barcode: str = "组合商品条码"
    title: str = "标题"
    account_name: str = "店铺名称"
    product_id: str = "商品ID"
    group_price: str = "拼单价"
    single_price: str = "单独买价"
    link: str = "商品链接"
    publish_start: str = "发布开始时间"
    publish_end: str = "发布结束时间"
    duration_seconds: str = "耗时秒"


class PddMarketingLogFieldNames(BaseModel):
    """PDD营销日志表 列名（投流昨日数据专用）。"""

    date: str = "日期"
    account_id: str = "店铺"
    product_id: str = "商品ID"
    traffic_result: str = "投流数据日志回写结果"
    traffic_error_reason: str = "投流数据日志报错原因"


class PddActivityLogFieldNames(BaseModel):
    """PDD活动日志表 — 店铺 + 商品ID 定位，仅活动步骤列。"""

    date: str = "日期"
    account_name: str = "店铺名称"
    product_id: str = "商品ID"
    limited_time_status: str = "限时限量购状态"
    limited_time_failure_reason: str = "限时限量购失败原因"
    activity_618_status: str = "618状态"
    activity_618_failure_reason: str = "618失败原因"
    activity_discount_status: str = "七折状态"
    activity_discount_failure_reason: str = "七折失败原因"


class PddPriceCompareFieldNames(BaseModel):
    """拼多多比价定价表列名。"""

    merchant_code: str = "商品编码"
    min_price: str = "PDD控价下限价格"
    max_price: str = "PDD控价上限价格"
    retail_cost: str = "综合零售成本"
    pdd_pricing: str = "拼多多定价"
    pdd_control_price: str = "拼多多控价"


class PddPriceCompareConfig(BaseModel):
    enabled: bool = Field(default=True, description="是否从飞书「拼多多比价定价」读取定价/控价数据")
    table_id: str = Field(default="", description="拼多多比价定价 table_id")
    table_name: str = Field(default="拼多多比价定价", description="比价定价飞书表名")
    excel_relpath: str = Field(
        default="data/assets/pdd.xls",
        description="控价区间 Excel（下限/上限）",
    )
    pricing_excel_relpath: str = Field(
        default="data/assets/拼多多定价.xls",
        description="母商品定价 Excel",
    )
    control_excel_relpath: str = Field(
        default="data/assets/拼多多控价.xls",
        description="子商品控价 Excel",
    )
    prefer_feishu: bool = Field(default=True, description="运行时优先读飞书，而非本地 Excel")
    fallback_excel: bool = Field(
        default=False,
        description="飞书无数据时是否回退读本地 Excel（由 pipeline.excel_fallback_enabled 统一控制）",
    )
    cache_seconds: int = Field(default=300, ge=0, le=3600, description="飞书定价/控价缓存秒数")
    field_names: PddPriceCompareFieldNames = Field(default_factory=PddPriceCompareFieldNames)


class PddProductCatalogFieldNames(BaseModel):
    """拼多多所有商品飞书表列名。"""

    product_code: str = "商品编码"
    color_spec: str = "颜色规格"
    product_type: str = "商品类型"
    available_inventory: str = "可用库存"
    pricing: str = "拼多多定价"


class PddProductCatalogConfig(BaseModel):
    enabled: bool = Field(default=True, description="是否从飞书「拼多多比价定价」读取上架商品表")
    table_id: str = Field(default="", description="拼多多所有商品 table_id")
    table_name: str = Field(default="拼多多比价定价", description="上架商品飞书表名（与比价定价表合并）")
    excel_relpath: str = Field(
        default="data/assets/拼多多所有商品.xls",
        description="本地商品表 Excel 路径",
    )
    prefer_feishu: bool = Field(default=True, description="运行时优先读飞书")
    fallback_excel: bool = Field(default=False, description="飞书无数据时回退本地 Excel（由 pipeline.excel_fallback_enabled 统一控制）")
    cache_seconds: int = Field(default=300, ge=0, le=3600, description="飞书商品表缓存秒数")
    price_float_enabled: bool = Field(default=True, description="上架拼单价是否在定价基础上加随机浮动")
    price_float_min: float = Field(default=0.0, ge=0, description="定价浮动下限（元）")
    price_float_max: float = Field(default=5.0, ge=0, description="定价浮动上限（元）")
    field_names: PddProductCatalogFieldNames = Field(default_factory=PddProductCatalogFieldNames)


class PipelineIntegrationConfig(BaseModel):
    """整合链路相关运行时开关（写入 feishu.yaml）。"""

    excel_fallback_enabled: bool = Field(
        default=False,
        description="开启后飞书商品/定价表无数据时回退本地 Excel；关闭则一律不回退",
    )


class PddActivityLogConfig(BaseModel):
    enabled: bool = Field(default=True, description="是否启用 PDD 活动日志表")
    table_id: str = Field(default="", description="PDD活动日志表 table_id")
    table_name: str = Field(default="PDD活动日志表", description="整合链路活动日志表名")
    dedupe_field: str = Field(default="商品ID", description="检索字段（与店铺名称组合定位唯一行）")
    activity_618_id: str = Field(default="20981", description="618 大促活动 ID")
    activity_discount_id: str = Field(default="21365", description="限量七折活动 ID")
    lookup_retries: int = Field(default=6, ge=1, le=20)
    lookup_interval_seconds: float = Field(default=5.0, ge=0.5, le=30.0)
    seed_on_listing: bool = Field(
        default=True,
        description="上架成功后预建活动日志行（仅商品标识+活动未执行，不含上架状态）",
    )
    immediate_find_retries: int = Field(
        default=2,
        ge=1,
        le=10,
        description="限时限量购回写时查活动表已有行的重试次数（上架后紧接执行，行应已预建）",
    )
    limited_time_status_options: list[str] = Field(
        default_factory=lambda: ["进行中", "失败", "未执行"],
    )
    activity_register_status_options: list[str] = Field(
        default_factory=lambda: ["报名成功", "活动下线", "失败", "未执行"],
    )
    field_names: PddActivityLogFieldNames = Field(default_factory=PddActivityLogFieldNames)


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
    traffic_metric_columns: list[str] = Field(
        default_factory=lambda: list(DEFAULT_TRAFFIC_METRIC_COLUMNS),
        description="投流推广列表右侧指标列（飞书表头名，与拼多多一致）",
    )
    field_names: PddMarketingLogFieldNames = Field(default_factory=PddMarketingLogFieldNames)


class PddPromotionLogFieldNames(BaseModel):
    """PDD推广日志表列名。"""

    date: str = "日期"
    account_name: str = "店铺名称"
    product_id: str = "商品ID"
    result: str = "推广结果"
    message: str = "备注"
    failure_reason: str = "失败原因"
    run_id: str = "运行ID"


class PddPromotionLogConfig(BaseModel):
    enabled: bool = Field(default=True, description="是否启用 PDD 推广日志表")
    table_id: str = Field(default="", description="PDD推广日志表 table_id")
    table_name: str = Field(default="PDD推广日志表", description="推广日志飞书表名")
    result_options: list[str] = Field(default_factory=lambda: ["成功", "失败"])
    field_names: PddPromotionLogFieldNames = Field(default_factory=PddPromotionLogFieldNames)

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_table(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if not str(out.get("table_id") or "").strip():
            legacy = str(out.get("success_table_id") or out.get("failure_table_id") or "").strip()
            if legacy:
                out["table_id"] = legacy
        if not out.get("result_options"):
            opts = out.get("success_result_options")
            if isinstance(opts, list) and opts:
                merged = list(dict.fromkeys([*opts, "失败"]))
                out["result_options"] = merged
        return out


class PddUploadLogConfig(BaseModel):
    enabled: bool = Field(
        default=False,
        description="上架核验成功后是否异步写入 PDD 上传日志表",
    )
    table_id: str = Field(
        default="",
        description="PDD发布日志表 table_id",
    )
    table_name: str = Field(
        default="PDD发布日志表",
        description="上架成功写入的飞书表名",
    )
    failure_table_id: str = Field(
        default="",
        description="淘宝+拼多多发布日志表（失败）table_id",
    )
    failure_table_name: str = Field(
        default="淘宝+拼多多发布日志表（失败）",
        description="上架失败/跳过写入的飞书表名（与淘宝共用）",
    )
    failure_record_type_options: list[str] = Field(
        default_factory=lambda: ["失败", "跳过"],
        description="失败表「记录类型」单选选项",
    )
    failure_report_platform_options: list[str] = Field(
        default_factory=lambda: ["拼多多", "淘宝"],
        description="失败表「报错平台」单选选项",
    )
    failure_default_report_platform: str = Field(
        default="拼多多",
        description="失败表「报错平台」默认值（PDD 上架失败写入时使用）",
    )
    failure_field_names: PddUploadFailureLogFieldNames = Field(
        default_factory=PddUploadFailureLogFieldNames,
    )
    dedupe_field: str = Field(
        default="商品ID",
        description="幂等去重字段名",
    )
    log_spec_sku_rows_enabled: bool = Field(
        default=False,
        description="上架成功时是否按规格编码展开写入发布日志（1 商品摘要 + 每条规格 1 行）",
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
        default=False,
        description="限时限量购完成后按商品ID回写飞书（默认关闭；发布日志表仅记录上架）",
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
        default=False,
        description="活动报名完成后按商品ID回写飞书（默认关闭；后续独立营销表）",
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
        default=False,
        description="推广任务完成后按商品ID回写飞书（默认关闭；后续独立营销表）",
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
        default="http://127.0.0.1:8010/api/feishu/oauth/callback",
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
    pdd_activity_log: PddActivityLogConfig = Field(default_factory=PddActivityLogConfig)
    pdd_marketing_log: PddMarketingLogConfig = Field(default_factory=PddMarketingLogConfig)
    pdd_promotion_log: PddPromotionLogConfig = Field(default_factory=PddPromotionLogConfig)
    pdd_price_compare: PddPriceCompareConfig = Field(default_factory=PddPriceCompareConfig)
    pdd_product_catalog: PddProductCatalogConfig = Field(default_factory=PddProductCatalogConfig)
    pipeline: PipelineIntegrationConfig = Field(default_factory=PipelineIntegrationConfig)


class FeishuConfig(BaseModel):
    app_id: str
    app_secret: str
    oauth_redirect_uri: str = "http://127.0.0.1:8010/api/feishu/oauth/callback"
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
    pdd_activity_log: PddActivityLogConfig = Field(default_factory=PddActivityLogConfig)
    pdd_marketing_log: PddMarketingLogConfig = Field(default_factory=PddMarketingLogConfig)
    pdd_promotion_log: PddPromotionLogConfig = Field(default_factory=PddPromotionLogConfig)
    pdd_price_compare: PddPriceCompareConfig = Field(default_factory=PddPriceCompareConfig)
    pdd_product_catalog: PddProductCatalogConfig = Field(default_factory=PddProductCatalogConfig)
    pipeline: PipelineIntegrationConfig = Field(default_factory=PipelineIntegrationConfig)


def excel_fallback_enabled(cfg: FeishuConfig | None = None) -> bool:
    """整合链路 Excel 回退总开关。"""
    cfg = cfg or load_feishu_config()
    return bool(cfg.pipeline.excel_fallback_enabled)


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

    pdd_activity_log = yaml_cfg.pdd_activity_log
    if "pdd_activity_log" in raw and isinstance(raw.get("pdd_activity_log"), dict):
        pdd_activity_log = PddActivityLogConfig.model_validate(raw["pdd_activity_log"])

    pdd_price_compare = yaml_cfg.pdd_price_compare
    if "pdd_price_compare" in raw and isinstance(raw.get("pdd_price_compare"), dict):
        pdd_price_compare = PddPriceCompareConfig.model_validate(raw["pdd_price_compare"])

    pdd_promotion_log = yaml_cfg.pdd_promotion_log
    if "pdd_promotion_log" in raw and isinstance(raw.get("pdd_promotion_log"), dict):
        pdd_promotion_log = PddPromotionLogConfig.model_validate(raw["pdd_promotion_log"])

    pdd_product_catalog = yaml_cfg.pdd_product_catalog
    if "pdd_product_catalog" in raw and isinstance(raw.get("pdd_product_catalog"), dict):
        pdd_product_catalog = PddProductCatalogConfig.model_validate(raw["pdd_product_catalog"])

    pipeline = yaml_cfg.pipeline
    if "pipeline" in raw and isinstance(raw.get("pipeline"), dict):
        pipeline = PipelineIntegrationConfig.model_validate(raw["pipeline"])

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
        pdd_activity_log=pdd_activity_log,
        pdd_marketing_log=pdd_marketing_log,
        pdd_promotion_log=pdd_promotion_log,
        pdd_price_compare=pdd_price_compare,
        pdd_product_catalog=pdd_product_catalog,
        pipeline=pipeline,
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
    """解析到 PDD 发布日志表后，把 table_id 写回 feishu.yaml。"""
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


def save_pdd_upload_failure_table_id_to_config(table_id: str, path: Path | None = None) -> None:
    """解析到淘宝+拼多多发布失败日志表后，把 failure_table_id 写回 feishu.yaml。"""
    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    data: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    pdd_raw = data.get("pdd_upload_log")
    if not isinstance(pdd_raw, dict):
        pdd_raw = {}
    pdd_raw["failure_table_id"] = table_id
    data["pdd_upload_log"] = pdd_raw
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def save_pdd_activity_table_id_to_config(table_id: str, path: Path | None = None) -> None:
    """解析到 PDD 活动日志表后，把 table_id 写回 feishu.yaml。"""
    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    data: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    activity_raw = data.get("pdd_activity_log")
    if not isinstance(activity_raw, dict):
        activity_raw = {}
    activity_raw["table_id"] = table_id
    data["pdd_activity_log"] = activity_raw
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def save_pdd_price_compare_table_id_to_config(table_id: str, path: Path | None = None) -> None:
    """解析到拼多多比价定价表后，把 table_id 写回 feishu.yaml。"""
    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    data: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    compare_raw = data.get("pdd_price_compare")
    if not isinstance(compare_raw, dict):
        compare_raw = {}
    compare_raw["table_id"] = table_id
    data["pdd_price_compare"] = compare_raw
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


def save_pdd_product_catalog_table_id_to_config(table_id: str, path: Path | None = None) -> None:
    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    data: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    catalog_raw = data.get("pdd_product_catalog")
    if not isinstance(catalog_raw, dict):
        catalog_raw = {}
    catalog_raw["table_id"] = table_id
    data["pdd_product_catalog"] = catalog_raw
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def save_pipeline_excel_fallback_to_config(enabled: bool, path: Path | None = None) -> None:
    """整合链路：写入 Excel 回退总开关到 feishu.yaml。"""
    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    data: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    pipeline_raw = data.get("pipeline")
    if not isinstance(pipeline_raw, dict):
        pipeline_raw = {}
    pipeline_raw["excel_fallback_enabled"] = bool(enabled)
    data["pipeline"] = pipeline_raw
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def save_pdd_upload_log_spec_rows_to_config(enabled: bool, path: Path | None = None) -> None:
    """上架成功日志：写入「按规格编码展开」开关到 feishu.yaml。"""
    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    data: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    upload_raw = data.get("pdd_upload_log")
    if not isinstance(upload_raw, dict):
        upload_raw = {}
    upload_raw["log_spec_sku_rows_enabled"] = bool(enabled)
    data["pdd_upload_log"] = upload_raw
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def save_pdd_promotion_table_id_to_config(table_id: str, path: Path | None = None) -> None:
    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    data: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    promo_raw = data.get("pdd_promotion_log")
    if not isinstance(promo_raw, dict):
        promo_raw = {}
    promo_raw["table_id"] = table_id
    data["pdd_promotion_log"] = promo_raw
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def save_pdd_marketing_log_schedule_to_config(
    *,
    traffic_report_enabled: bool | None = None,
    traffic_report_schedule_hour: int | None = None,
    traffic_report_schedule_minute: int | None = None,
    traffic_report_account_ids: list[str] | None = None,
    path: Path | None = None,
) -> None:
    """更新 PDD 营销日志表投流定时任务配置并写回 feishu.yaml。"""
    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    data: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    marketing_raw = data.get("pdd_marketing_log")
    if not isinstance(marketing_raw, dict):
        marketing_raw = {}
    if traffic_report_enabled is not None:
        marketing_raw["traffic_report_enabled"] = bool(traffic_report_enabled)
    if traffic_report_schedule_hour is not None:
        marketing_raw["traffic_report_schedule_hour"] = int(traffic_report_schedule_hour)
    if traffic_report_schedule_minute is not None:
        marketing_raw["traffic_report_schedule_minute"] = int(traffic_report_schedule_minute)
    if traffic_report_account_ids is not None:
        marketing_raw["traffic_report_account_ids"] = [
            str(aid).strip() for aid in traffic_report_account_ids if str(aid).strip()
        ]
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
