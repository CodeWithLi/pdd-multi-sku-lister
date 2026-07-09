"""提交前 AI 改标题：数据库配置读写服务。"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from pdd_agent.db.models import ListingSubmitAiTitleConfigORM
from pdd_agent.db.session import is_database_available, session_scope

DEFAULT_SUBMIT_AI_TITLE_PROMPT = (
    "你是淘宝文具运营。只回1个标题，22-28个汉字，最多60字节，汉字2字节英文1字节。\n"
    "用真实品类+颜色/IP/风格+学生/上学+大容量/文具收纳词。\n"
    "若用户给出已生成标题，必须换卖点和关键词，不能只调整词序。\n"
    "禁解释、前缀、编号、Markdown、JSON、备选；不把店铺名当商品品牌；"
    "不虚构材质、尺寸、赠品、授权、年龄；少堆内部编码。"
)


@dataclass(slots=True)
class SubmitAiTitleConfig:
    enabled: bool = False
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    prompt: str = DEFAULT_SUBMIT_AI_TITLE_PROMPT
    temperature: float = 0.3
    max_image_count: int = 3


def _normalize_config(cfg: SubmitAiTitleConfig) -> SubmitAiTitleConfig:
    provider = str(cfg.provider or "deepseek").strip() or "deepseek"
    model = str(cfg.model or "deepseek-chat").strip() or "deepseek-chat"
    base_url = str(cfg.base_url or "https://api.deepseek.com/v1").strip() or "https://api.deepseek.com/v1"
    prompt = str(cfg.prompt or DEFAULT_SUBMIT_AI_TITLE_PROMPT).strip() or DEFAULT_SUBMIT_AI_TITLE_PROMPT
    temperature = float(cfg.temperature if cfg.temperature is not None else 0.3)
    if temperature < 0:
        temperature = 0.0
    if temperature > 2:
        temperature = 2.0
    max_image_count = int(cfg.max_image_count or 1)
    if max_image_count < 1:
        max_image_count = 1
    if max_image_count > 5:
        max_image_count = 5
    return SubmitAiTitleConfig(
        enabled=bool(cfg.enabled),
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=str(cfg.api_key or "").strip(),
        prompt=prompt,
        temperature=temperature,
        max_image_count=max_image_count,
    )


def _default_config() -> SubmitAiTitleConfig:
    return SubmitAiTitleConfig()


def _to_dataclass(row: ListingSubmitAiTitleConfigORM) -> SubmitAiTitleConfig:
    return _normalize_config(
        SubmitAiTitleConfig(
            enabled=bool(row.enabled),
            provider=str(row.provider or ""),
            model=str(row.model or ""),
            base_url=str(row.base_url or ""),
            api_key=str(row.api_key or ""),
            prompt=str(row.prompt or ""),
            temperature=float(row.temperature or 0.3),
            max_image_count=int(row.max_image_count or 3),
        )
    )


def get_submit_ai_title_config() -> SubmitAiTitleConfig:
    """读取配置；数据库不可用时返回默认值。"""
    if not is_database_available():
        return _default_config()
    with session_scope() as session:
        row = session.get(ListingSubmitAiTitleConfigORM, "default")
        if row:
            return _to_dataclass(row)
        cfg = _default_config()
        session.add(
            ListingSubmitAiTitleConfigORM(
                config_id="default",
                enabled=cfg.enabled,
                provider=cfg.provider,
                model=cfg.model,
                base_url=cfg.base_url,
                api_key=cfg.api_key,
                prompt=cfg.prompt,
                temperature=cfg.temperature,
                max_image_count=cfg.max_image_count,
            )
        )
        return cfg


def update_submit_ai_title_config(
    *,
    enabled: bool | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    prompt: str | None = None,
    temperature: float | None = None,
    max_image_count: int | None = None,
) -> SubmitAiTitleConfig:
    """更新提交前 AI 标题配置；数据库不可用时仅返回内存结果。"""
    current = get_submit_ai_title_config()
    payload = asdict(current)
    if enabled is not None:
        payload["enabled"] = bool(enabled)
    if provider is not None:
        payload["provider"] = str(provider or "").strip()
    if model is not None:
        payload["model"] = str(model or "").strip()
    if base_url is not None:
        payload["base_url"] = str(base_url or "").strip()
    if api_key is not None:
        payload["api_key"] = str(api_key or "").strip()
    if prompt is not None:
        payload["prompt"] = str(prompt or "").strip()
    if temperature is not None:
        payload["temperature"] = float(temperature)
    if max_image_count is not None:
        payload["max_image_count"] = int(max_image_count)
    normalized = _normalize_config(SubmitAiTitleConfig(**payload))
    if not is_database_available():
        return normalized
    with session_scope() as session:
        row = session.get(ListingSubmitAiTitleConfigORM, "default")
        if not row:
            row = ListingSubmitAiTitleConfigORM(config_id="default")
            session.add(row)
        row.enabled = normalized.enabled
        row.provider = normalized.provider
        row.model = normalized.model
        row.base_url = normalized.base_url
        row.api_key = normalized.api_key
        row.prompt = normalized.prompt
        row.temperature = normalized.temperature
        row.max_image_count = normalized.max_image_count
    return normalized
