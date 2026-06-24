"""企业微信集成配置（独立 YAML）。"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

from pdd_agent.paths import CONFIG_DIR

DEFAULT_WECOM_CONFIG_PATH = CONFIG_DIR / "wecom.yaml"
_WEBHOOK_KEY_RE = re.compile(r"key=([0-9a-f-]{8,})", re.I)


class WecomConfig(BaseModel):
    enabled: bool = False
    webhook_url: str = ""
    notify_on_listing_failed: bool = False
    notify_on_pipeline_failed: bool = False

    @model_validator(mode="after")
    def normalize(self) -> "WecomConfig":
        self.webhook_url = str(self.webhook_url or "").strip()
        return self


def _load_yaml_raw(path: Path | None = None) -> tuple[Path, dict]:
    cfg_path = path or Path(os.getenv("WECOM_CONFIG_PATH", DEFAULT_WECOM_CONFIG_PATH))
    raw: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
            raw = loaded if isinstance(loaded, dict) else {}
    return cfg_path, raw


def load_wecom_config(path: Path | None = None) -> WecomConfig:
    _, raw = _load_yaml_raw(path)
    return WecomConfig.model_validate(raw)


def save_wecom_config(config: WecomConfig, path: Path | None = None) -> WecomConfig:
    normalized = WecomConfig.model_validate(config.model_dump())
    cfg_path, raw = _load_yaml_raw(path)
    raw.update(normalized.model_dump())
    raw.pop("mentioned_list", None)
    raw.pop("mentioned_mobile_list", None)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
    return normalized


def wecom_configured(cfg: WecomConfig | None = None) -> bool:
    cfg = cfg or load_wecom_config()
    return bool(cfg.enabled and cfg.webhook_url)


def mask_webhook_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    match = _WEBHOOK_KEY_RE.search(text)
    if not match:
        if len(text) <= 12:
            return "***"
        return f"{text[:8]}...{text[-4:]}"
    key = match.group(1)
    if len(key) <= 12:
        masked_key = "***"
    else:
        masked_key = f"{key[:4]}****{key[-4:]}"
    return _WEBHOOK_KEY_RE.sub(f"key={masked_key}", text)
