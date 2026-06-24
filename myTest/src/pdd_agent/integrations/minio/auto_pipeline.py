"""RabbitMQ 上传批次完成后，按配置自动触发整合链路。"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.minio.config import DEFAULT_MINIO_CONFIG_PATH

logger = get_logger(__name__)

AutoTriggerMode = Literal["new_product_folder", "append_to_product", "all"]

_RECENT_LOCK = threading.Lock()
_RECENT_TRIGGERS: dict[str, float] = {}
_DEDUP_SECONDS = 120


class AutoPipelineConfig(BaseModel):
    enabled: bool = False
    trigger_mode: AutoTriggerMode = "new_product_folder"
    account_id: str = ""
    activity_ids: list[str] = Field(default_factory=lambda: ["20981"])
    category_keyword: str = "玩偶"
    auto_promotion: bool = True
    auto_limited_time_setup: bool = True
    continue_after_limited_time_failure: bool = False
    continue_after_activity_failure: bool = False
    demo_mode: bool = True
    activity_delay_hours: float = Field(default=24.0, ge=0)
    slot_alignment_test: bool = True
    material_source: str = "minio"
    auto_sync_minio: bool = True

    @model_validator(mode="after")
    def normalize(self) -> "AutoPipelineConfig":
        self.activity_ids = list(dict.fromkeys(str(x).strip() for x in self.activity_ids if str(x).strip()))
        self.account_id = str(self.account_id or "").strip()
        self.category_keyword = str(self.category_keyword or "玩偶").strip() or "玩偶"
        self.material_source = str(self.material_source or "minio").strip().lower() or "minio"
        return self


def _load_minio_yaml_raw(path: Path | None = None) -> tuple[Path, dict]:
    cfg_path = path or Path(os.getenv("MINIO_CONFIG_PATH", DEFAULT_MINIO_CONFIG_PATH))
    raw: dict = {}
    if cfg_path.is_file():
        with open(cfg_path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
            raw = loaded if isinstance(loaded, dict) else {}
    return cfg_path, raw


def load_auto_pipeline_config(path: Path | None = None) -> AutoPipelineConfig:
    _, raw = _load_minio_yaml_raw(path)
    section = raw.get("auto_pipeline")
    if not isinstance(section, dict):
        return AutoPipelineConfig()
    return AutoPipelineConfig.model_validate(section)


def save_auto_pipeline_config(config: AutoPipelineConfig, path: Path | None = None) -> AutoPipelineConfig:
    normalized = AutoPipelineConfig.model_validate(config.model_dump())
    cfg_path, raw = _load_minio_yaml_raw(path)
    raw["auto_pipeline"] = normalized.model_dump()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
    return normalized


def _allowed_change_types(mode: AutoTriggerMode) -> frozenset[str]:
    if mode == "new_product_folder":
        # 含「新增套图」：首次上传 BD713719/第一套图/商品 整路径时，索引里尚无该套图
        return frozenset({"new_product_folder", "new_image_set"})
    if mode == "append_to_product":
        return frozenset({"append_to_product"})
    return frozenset({"new_product_folder", "append_to_product", "new_image_set"})


def extract_auto_pipeline_product_codes(
    batch_summary: dict[str, Any],
    mode: AutoTriggerMode,
) -> list[str]:
    allowed = _allowed_change_types(mode)
    codes: list[str] = []
    for group in batch_summary.get("groups") or []:
        if not isinstance(group, dict):
            continue
        change_type = str(group.get("change_type") or "")
        if change_type not in allowed:
            continue
        selector = str(group.get("selector") or "").strip()
        product_code = str(group.get("product_code") or "").strip()
        if selector and product_code:
            codes.append(f"{selector}/{product_code}")
    return list(dict.fromkeys(codes))


def _dedup_key(account_id: str, product_codes: list[str]) -> str:
    return f"{account_id}|{'|'.join(sorted(product_codes))}"


def _mark_dedup(key: str) -> bool:
    """若近期已触发过相同任务则返回 True（应跳过）。"""
    now = time.time()
    with _RECENT_LOCK:
        stale = [k for k, ts in _RECENT_TRIGGERS.items() if now - ts > _DEDUP_SECONDS]
        for k in stale:
            _RECENT_TRIGGERS.pop(k, None)
        if key in _RECENT_TRIGGERS:
            return True
        _RECENT_TRIGGERS[key] = now
    return False


def _sync_minio_blocking(product_codes: list[str]) -> str:
    from pdd_agent.api.services.minio_sync_service import (
        get_active_minio_sync_job,
        get_minio_sync_job,
        start_minio_sync_job,
    )

    job_id = ""
    try:
        job = start_minio_sync_job(product_codes)
        job_id = job.job_id
    except RuntimeError:
        active = get_active_minio_sync_job()
        if active and active.status in {"pending", "running"}:
            job_id = active.job_id
        else:
            return "无法启动 MinIO 同步"

    deadline = time.time() + 300
    while time.time() < deadline:
        current = get_minio_sync_job(job_id)
        if not current:
            return "MinIO 同步任务丢失"
        if current.status == "success":
            return ""
        if current.status == "failed":
            return current.error or "MinIO 同步失败"
        time.sleep(0.5)
    return "MinIO 同步超时"


def _run_auto_pipeline(
    *,
    account_id: str,
    product_codes: list[str],
    cfg: AutoPipelineConfig,
) -> None:
    try:
        from pdd_agent.api.services.config_service import get_account_or_none
        from pdd_agent.api.services.pipeline_service import start_integrated_pipeline
        from pdd_agent.db.session import is_database_available

        if not is_database_available():
            logger.warning("auto pipeline skipped: database unavailable")
            return
        if not get_account_or_none(account_id):
            logger.warning("auto pipeline skipped: unknown account %s", account_id)
            return

        material_source = cfg.material_source or "minio"
        if material_source == "minio" and cfg.auto_sync_minio:
            sync_err = _sync_minio_blocking(product_codes)
            if sync_err:
                logger.error("auto pipeline minio sync failed: %s", sync_err)
                return

        pipeline = start_integrated_pipeline(
            account_id=account_id,
            product_codes=product_codes,
            activity_ids=cfg.activity_ids,
            category_keyword=cfg.category_keyword,
            auto_promotion=cfg.auto_promotion,
            auto_limited_time_setup=cfg.auto_limited_time_setup,
            continue_after_limited_time_failure=cfg.continue_after_limited_time_failure,
            continue_after_activity_failure=cfg.continue_after_activity_failure,
            activity_delay_hours=0 if cfg.demo_mode else cfg.activity_delay_hours,
            demo_mode=cfg.demo_mode,
            slot_alignment_test=cfg.slot_alignment_test,
            material_source=material_source,
        )
        logger.info(
            "auto pipeline triggered pipeline_id=%s account=%s products=%s",
            pipeline.get("pipeline_id"),
            account_id,
            product_codes,
        )
    except Exception:
        logger.exception("auto pipeline trigger failed account=%s products=%s", account_id, product_codes)


def format_auto_pipeline_reason(reason: str) -> str:
    labels = {
        "disabled": "自动上架未开启",
        "missing_account_id": "未配置店铺，请在「自动化配置」中选择店铺并保存",
        "missing_activity_ids": "未配置营销活动",
        "no_matching_groups": "上传类型与触发范围不匹配（当前为追加图片，需选「仅追加文件」或「都可以」）",
        "dedup": "近期已触发过相同商品（120 秒内去重）",
        "no_indexed_files": "没有成功索引的图片",
        "batch_not_success": "上传批次未成功，未触发自动上架",
    }
    return labels.get(str(reason or "").strip(), reason or "未知原因")


def maybe_trigger_auto_pipeline(batch_summary: dict[str, Any]) -> dict[str, Any]:
    """根据 auto_pipeline 配置决定是否后台启动整合链路。"""
    result: dict[str, Any] = {"triggered": False}
    cfg = load_auto_pipeline_config()
    if not cfg.enabled:
        result["reason"] = "disabled"
        result["reason_label"] = format_auto_pipeline_reason("disabled")
        return result
    if batch_summary.get("status") not in {"success", "partial"}:
        result["reason"] = "batch_not_success"
        result["reason_label"] = format_auto_pipeline_reason("batch_not_success")
        return result
    if not int(batch_summary.get("indexed_file_count") or 0):
        result["reason"] = "no_indexed_files"
        result["reason_label"] = format_auto_pipeline_reason("no_indexed_files")
        return result

    account_id = cfg.account_id
    if not account_id:
        result["reason"] = "missing_account_id"
        result["reason_label"] = format_auto_pipeline_reason("missing_account_id")
        return result
    if not cfg.activity_ids:
        result["reason"] = "missing_activity_ids"
        result["reason_label"] = format_auto_pipeline_reason("missing_activity_ids")
        return result

    product_codes = extract_auto_pipeline_product_codes(batch_summary, cfg.trigger_mode)
    if not product_codes:
        result["reason"] = "no_matching_groups"
        result["trigger_mode"] = cfg.trigger_mode
        result["reason_label"] = format_auto_pipeline_reason("no_matching_groups")
        groups = batch_summary.get("groups") or []
        result["group_change_types"] = sorted(
            {str(g.get("change_type") or "") for g in groups if isinstance(g, dict) and g.get("change_type")}
        )
        return result

    dedup = _dedup_key(account_id, product_codes)
    if _mark_dedup(dedup):
        result["reason"] = "dedup"
        result["product_codes"] = product_codes
        result["reason_label"] = format_auto_pipeline_reason("dedup")
        return result

    thread = threading.Thread(
        target=_run_auto_pipeline,
        kwargs={"account_id": account_id, "product_codes": product_codes, "cfg": cfg},
        name="auto-pipeline-trigger",
        daemon=True,
    )
    thread.start()
    result["triggered"] = True
    result["product_codes"] = product_codes
    result["account_id"] = account_id
    result["trigger_mode"] = cfg.trigger_mode
    return result
