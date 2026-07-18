"""可选的拼多多上架修复流程。

旧流程默认不变；本模块只在 ``pdd_listing_quality_v2_enabled`` 开启时提供
标题合规、组合素材去重、规格命名、固定价格和发布后查询策略。
"""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

TITLE_MIN_PLATFORM_UNITS = 50
TITLE_MAX_PLATFORM_UNITS = 58
TITLE_MAX_GENERATION_ATTEMPTS = 3
TITLE_BANNED_TERMS = ("官方", "正版", "正品", "授权", "原版", "原装")


@dataclass(frozen=True)
class TitlePolicyResult:
    valid: bool
    title: str
    platform_units: int
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublishSearchStep:
    tab_text: str
    tab_key: str
    attempts: int
    refresh_on_not_found: bool
    captured_status: str


QUALITY_V2_PUBLISH_SEARCH_STEPS = (
    PublishSearchStep("在售中", "on_sale", 3, True, "captured"),
    PublishSearchStep("发布中", "publishing", 2, True, "publishing"),
    PublishSearchStep("已驳回", "rejected", 2, True, "rejected"),
    PublishSearchStep("草稿箱", "draft", 1, False, "draft"),
)


def quality_v2_enabled(cfg: Any | None = None) -> bool:
    """读取新流程总开关；调用方可传已加载配置，避免重复读文件。"""
    if cfg is None:
        from pdd_agent.integrations.feishu.config import load_feishu_config

        cfg = load_feishu_config()
    pipeline = getattr(cfg, "pipeline", None)
    return bool(getattr(pipeline, "pdd_listing_quality_v2_enabled", False))


def save_quality_v2_enabled(enabled: bool, path: Path | None = None) -> None:
    """只保存新流程开关，不改动旧流程的定价/规格开关。"""
    from pdd_agent.integrations.feishu.config import DEFAULT_FEISHU_CONFIG_PATH

    cfg_path = path or Path(os.getenv("FEISHU_CONFIG_PATH", DEFAULT_FEISHU_CONFIG_PATH))
    data: dict[str, Any] = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
    pipeline = data.get("pipeline")
    if not isinstance(pipeline, dict):
        pipeline = {}
    pipeline["pdd_listing_quality_v2_enabled"] = bool(enabled)
    data["pipeline"] = pipeline
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as file:
        yaml.dump(data, file, allow_unicode=True, default_flow_style=False, sort_keys=False)


def fixed_price_mode_enabled(cfg: Any | None = None) -> bool:
    """新流程强制原价相加；否则沿用旧的原价相加开关。"""
    if cfg is None:
        from pdd_agent.integrations.feishu.config import load_feishu_config

        cfg = load_feishu_config()
    pipeline = getattr(cfg, "pipeline", None)
    return quality_v2_enabled(cfg) or bool(
        getattr(pipeline, "original_sum_pricing_enabled", False)
    )


def title_platform_units(title: str) -> int:
    """按拼多多计数方式换算：ASCII 1 个字符，其余字符 2 个字符。"""
    return sum(1 if ord(char) < 128 else 2 for char in str(title or ""))


def validate_quality_v2_title(title: str) -> TitlePolicyResult:
    """校验 25-29 个汉字等价长度、禁标点和禁用宣传词。"""
    text = str(title or "").strip()
    units = title_platform_units(text)
    reasons: list[str] = []
    if units < TITLE_MIN_PLATFORM_UNITS:
        reasons.append(f"标题不足25个汉字等价长度（当前平台计数{units}）")
    elif units > TITLE_MAX_PLATFORM_UNITS:
        reasons.append(f"标题超过29个汉字等价长度（当前平台计数{units}）")

    punctuation = list(
        dict.fromkeys(
            char
            for char in text
            if unicodedata.category(char).startswith(("P", "S"))
        )
    )
    if punctuation:
        reasons.append(f"标题含标点或符号：{''.join(punctuation)}")

    banned = [term for term in TITLE_BANNED_TERMS if term in text]
    if banned:
        reasons.append(f"标题含禁用词：{'、'.join(banned)}")
    if not text and not reasons:
        reasons.append("标题为空")
    return TitlePolicyResult(
        valid=not reasons,
        title=text,
        platform_units=units,
        reasons=tuple(reasons),
    )


def _title_policy_prompt(base_prompt: str) -> str:
    banned = "、".join(TITLE_BANNED_TERMS)
    return (
        f"{base_prompt}\n\n"
        "本次必须满足：标题为25-29个汉字等价长度（平台计数50-58）；"
        "标题中不得出现任何标点或符号；"
        f"不得出现{banned}等宣传或授权字样。只返回最终标题。"
    )


def _title_retry_prompt(base_prompt: str, candidate: str, policy: TitlePolicyResult) -> str:
    issues = "；".join(policy.reasons)
    return (
        f"{_title_policy_prompt(base_prompt)}\n"
        f"上一次标题「{candidate}」不合规：{issues}。请重新生成，不要截断旧标题。"
    )


def generate_compliant_title(
    *,
    base_prompt: str,
    invoke: Callable[[str], dict[str, Any]],
    max_attempts: int = TITLE_MAX_GENERATION_ATTEMPTS,
) -> dict[str, Any]:
    """调用标题模型直到合规；耗尽次数后返回失败，禁止回退提交原标题。"""
    attempts = max(1, int(max_attempts or 1))
    prompt = _title_policy_prompt(base_prompt)
    diagnostics: list[dict[str, Any]] = []
    last_result: dict[str, Any] = {}

    for attempt in range(1, attempts + 1):
        last_result = dict(invoke(prompt) or {})
        candidate = str(last_result.get("title") or "").strip()
        if not candidate:
            last_result["quality_v2_attempts"] = diagnostics
            return last_result

        policy = validate_quality_v2_title(candidate)
        diagnostics.append(
            {
                "attempt": attempt,
                "title": candidate,
                "platform_units": policy.platform_units,
                "reasons": list(policy.reasons),
            }
        )
        if policy.valid:
            last_result["quality_v2_attempts"] = diagnostics
            last_result["quality_v2_title_valid"] = True
            return last_result
        prompt = _title_retry_prompt(base_prompt, candidate, policy)

    rejected = str(last_result.get("title") or "").strip()
    last_result["title"] = ""
    last_result["rejected_title"] = rejected
    last_result["reason"] = "title_policy_retries_exhausted"
    last_result["policy_failed"] = True
    last_result["quality_v2_attempts"] = diagnostics
    last_result["quality_v2_title_valid"] = False
    return last_result


def preview_dedupe_key(
    style_code: str,
    model_code: str,
    combo_stem: str,
    *,
    enabled: bool,
) -> tuple[str, str]:
    """新流程按套装内的实际子编码去重，避免所有套装折叠成一条。"""
    style = str(style_code or "").strip()
    model = str(model_code or "").strip()
    if not enabled or model != "套装":
        return style, model
    stem = Path(str(combo_stem or "")).stem.strip()
    parts = [part.strip().upper() for part in stem.split("+") if part.strip()]
    components = parts[1:] if len(parts) > 1 else parts
    return style, f"套装:{'+'.join(components)}"


def prefer_product_type_size_label(
    *,
    base_entry: Any | None,
    sub_entry: Any | None,
    fallback: str,
) -> str:
    """新流程中商品类型优先于颜色规格关键词，如“挂件”素材实际为“公仔”。"""
    if base_entry is None or sub_entry is None:
        return fallback
    base_code = str(getattr(base_entry, "code", "") or "").strip().upper()
    sub_code = str(getattr(sub_entry, "code", "") or "").strip().upper()
    if base_code and sub_code and base_code == sub_code:
        return fallback
    product_type = str(getattr(sub_entry, "product_type", "") or "").strip()
    if not product_type or product_type in {"亚克力", "半成品", "配件"}:
        return fallback
    base_type = str(getattr(base_entry, "product_type", "") or "").strip()
    if not base_type:
        return fallback
    return f"{base_type}+{product_type}"


def run_quality_v2_publish_search(
    *,
    search_tab: Callable[[PublishSearchStep], dict[str, Any]],
    search_all: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """依次查在售、发布中、驳回、草稿和全部，返回平台真实状态。"""
    searched: list[str] = []
    any_open_failed = False
    for step in QUALITY_V2_PUBLISH_SEARCH_STEPS:
        searched.append(step.tab_text)
        result = dict(search_tab(step) or {})
        if result.get("status") == "captured":
            result["status"] = step.captured_status
            result["searched_tabs"] = searched
            return result
        any_open_failed = any_open_failed or result.get("status") == "open_goods_list_failed"

    searched.append("全部")
    result = dict(search_all() or {})
    result["searched_tabs"] = searched
    if result.get("status") != "not_found":
        return result
    result["status"] = "open_goods_list_failed" if any_open_failed else "not_found"
    result["message"] = "已查询在售中、发布中、已驳回、草稿箱和全部，未找到本次商品记录，当前没有可复制的商品链接"
    return result


__all__ = [
    "PublishSearchStep",
    "TitlePolicyResult",
    "fixed_price_mode_enabled",
    "generate_compliant_title",
    "prefer_product_type_size_label",
    "preview_dedupe_key",
    "quality_v2_enabled",
    "run_quality_v2_publish_search",
    "save_quality_v2_enabled",
    "title_platform_units",
    "validate_quality_v2_title",
]
