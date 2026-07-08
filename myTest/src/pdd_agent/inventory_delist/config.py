"""库存下架模块 — 配置读写。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from pdd_agent.paths import CONFIG_DIR, PROJECT_ROOT

CONFIG_BASENAME = "inventory_delist_schedule.yaml"
CONFIG_PATH = CONFIG_DIR / CONFIG_BASENAME
EXAMPLE_PATH = CONFIG_DIR / "inventory_delist_schedule.example.yaml"

ExecutionMode = Literal["parallel", "sequential"]


class InventoryDelistScheduleConfig(BaseModel):
    enabled: bool = False
    interval_hours: float = Field(default=6.0, ge=0.5, le=168.0)
    account_ids: list[str] = Field(default_factory=list)
    execution_mode: ExecutionMode = "parallel"
    delist_spec_code_search_enabled: bool = False


def _ensure_config_file() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.is_file():
        if EXAMPLE_PATH.is_file():
            CONFIG_PATH.write_text(EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            CONFIG_PATH.write_text(
                "enabled: false\ninterval_hours: 6\naccount_ids: []\n"
                "execution_mode: parallel\ndelist_spec_code_search_enabled: false\n",
                encoding="utf-8",
            )
    return CONFIG_PATH


def load_inventory_delist_config() -> InventoryDelistScheduleConfig:
    path = _ensure_config_file()
    raw: dict[str, Any] = {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw = loaded
    except OSError:
        pass
    mode = str(raw.get("execution_mode") or "parallel").strip().lower()
    if mode not in {"parallel", "sequential"}:
        mode = "parallel"
    account_ids = [
        str(aid).strip()
        for aid in (raw.get("account_ids") or [])
        if str(aid).strip()
    ]
    try:
        interval = float(raw.get("interval_hours") or 6)
    except (TypeError, ValueError):
        interval = 6.0
    interval = max(0.5, min(168.0, interval))
    return InventoryDelistScheduleConfig(
        enabled=bool(raw.get("enabled")),
        interval_hours=interval,
        account_ids=account_ids,
        execution_mode=mode,  # type: ignore[arg-type]
        delist_spec_code_search_enabled=bool(raw.get("delist_spec_code_search_enabled")),
    )


def save_inventory_delist_config(cfg: InventoryDelistScheduleConfig) -> InventoryDelistScheduleConfig:
    path = _ensure_config_file()
    payload = {
        "enabled": bool(cfg.enabled),
        "interval_hours": float(cfg.interval_hours),
        "account_ids": [str(aid).strip() for aid in cfg.account_ids if str(aid).strip()],
        "execution_mode": cfg.execution_mode,
        "delist_spec_code_search_enabled": bool(cfg.delist_spec_code_search_enabled),
    }
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return load_inventory_delist_config()


def state_file_path() -> Path:
    data_dir = (PROJECT_ROOT / "data").resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "inventory_delist_state.json"
