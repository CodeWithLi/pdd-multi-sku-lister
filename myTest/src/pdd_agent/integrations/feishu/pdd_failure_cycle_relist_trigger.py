"""失败日志循环上架：占用后触发整合链路。"""

from __future__ import annotations

from typing import Any

from pdd_agent.browser.sync_job import run_sync_browser_job
from pdd_agent.api.services.pipeline_service import start_integrated_pipeline
from pdd_agent.core.account_display import resolve_cycle_relist_account_id
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_account_config, update_integrated_pipeline
from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    PddFailureCycleRelistWatchConfig,
    load_feishu_config,
)
from pdd_agent.integrations.feishu.listing_feishu_catalog import codes_match, normalize_listing_code
from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_claim import try_claim_cycle_relist
from pdd_agent.skills.listing.catalog import _parse_listing_target_product_selector

logger = get_logger(__name__)


def resolve_default_pipeline_activity_ids(config: FeishuConfig | None = None) -> list[str]:
    cfg = config or load_feishu_config()
    act = cfg.pdd_activity_log
    ids: list[str] = []
    for value in (act.activity_618_id, act.activity_discount_id):
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)
    return ids


def _catalog_index(*, material_source: str) -> dict[str, frozenset[str]]:
    source = str(material_source or "").strip().lower()
    if source == "minio":
        from pdd_agent.integrations.minio.catalog import build_minio_catalog_set_index

        return build_minio_catalog_set_index()
    from pdd_agent.db.repositories import build_catalog_set_index

    return build_catalog_set_index(load_yaml_settings())


def resolve_listing_selectors_for_merchant_code(
    merchant_code: str,
    *,
    material_source: str = "",
) -> list[str]:
    """把失败日志「商品编码」解析为整合链路 product_codes（母编码/套图/商品编码）。"""
    raw = str(merchant_code or "").strip()
    if not raw:
        return []

    if _parse_listing_target_product_selector(raw):
        return [raw]

    target_code = normalize_listing_code(raw)
    if not target_code:
        return []

    catalog_index = _catalog_index(material_source=material_source)
    exact_matches: list[str] = []
    fuzzy_matches: list[str] = []
    for set_selector, codes in catalog_index.items():
        for product_code in codes:
            pc = str(product_code or "").strip()
            if not pc:
                continue
            selector = f"{set_selector}/{pc}"
            if pc == target_code or normalize_listing_code(pc) == target_code:
                exact_matches.append(selector)
            elif codes_match(target_code, pc):
                fuzzy_matches.append(selector)

    if exact_matches:
        return list(dict.fromkeys(exact_matches))
    return list(dict.fromkeys(fuzzy_matches))


def check_merchant_code_already_on_sale(
    *,
    account_id: str,
    merchant_code: str,
) -> dict[str, Any]:
    """在拼多多商品列表按商品编码搜索，判断是否已存在在售商品。"""
    aid = str(account_id or "").strip()
    code = str(merchant_code or "").strip()
    if not aid or not code:
        return {"checked": False, "listed": False, "error": "account_id 或 merchant_code 为空"}

    settings = load_yaml_settings()
    account = get_account_config(settings, aid)
    if not account or not account.enabled:
        return {"checked": False, "listed": False, "error": f"店铺不可用: {aid}"}

    def _job(page):
        from pdd_agent.skills.listing.upload import (
            _click_goods_search,
            _fill_goods_merchant_code_filter,
            _open_goods_list,
            _parse_goods_list_matches,
            _reset_goods_list_filters,
            _set_goods_filter,
        )

        if not _open_goods_list(page, aid, tab_text="在售中"):
            return {"checked": False, "listed": False, "error": "无法打开在售商品列表"}
        _reset_goods_list_filters(page)
        fill = _fill_goods_merchant_code_filter(page, code)
        filled = bool(fill.get("filled"))
        if not filled:
            filled = bool(_set_goods_filter(page, "商品编码", code))
        if not filled:
            return {"checked": False, "listed": False, "error": "无法填写商品编码搜索框"}
        _click_goods_search(page)
        matches = _parse_goods_list_matches(page, code, "")
        if not matches:
            return {"checked": True, "listed": False, "matches": 0}
        selected = matches[0]
        return {
            "checked": True,
            "listed": True,
            "matches": len(matches),
            "pdd_product_id": str(selected.get("pdd_product_id") or ""),
            "list_status": str(selected.get("list_status") or ""),
        }

    return run_sync_browser_job(settings, account, _job)


def process_failure_cycle_relist_candidate(
    candidate: dict[str, Any],
    *,
    config: FeishuConfig | None = None,
    watch: PddFailureCycleRelistWatchConfig | None = None,
    skip_claim: bool = False,
    trigger_source: str = "auto_watch",
) -> dict[str, Any]:
    """占用失败日志行并启动整合链路。旧失败日志保持勾选，不再修改。"""
    cfg = config or load_feishu_config()
    watch_cfg = watch or cfg.pdd_upload_log.failure_cycle_relist_watch
    record_id = str(candidate.get("record_id") or "").strip()
    merchant_code = str(candidate.get("merchant_code") or "").strip()
    account_name = str(candidate.get("account_name") or "").strip()
    account_id_hint = str(candidate.get("account_id") or "").strip()
    report_platform = str(candidate.get("report_platform") or "").strip()

    base = {
        "ok": False,
        "record_id": record_id,
        "merchant_code": merchant_code,
        "account_name": account_name,
        "account_id": "",
        "pipeline_id": "",
        "claim": {},
        "error": "",
        "skipped": False,
        "reason": "",
    }

    if not record_id:
        base["error"] = "record_id 为空"
        return base

    allowed_platforms = {
        str(x).strip()
        for x in (watch_cfg.pipeline_report_platforms or [])
        if str(x).strip()
    }
    if allowed_platforms and report_platform and report_platform not in allowed_platforms:
        base.update(ok=True, skipped=True, reason="report_platform_filtered")
        return base

    claim_result = None
    account_id, account_error = resolve_cycle_relist_account_id(
        account_name=account_name,
        account_id=account_id_hint,
    )
    if not account_id:
        base["error"] = account_error or "无法识别目标店铺"
        return base
    base["account_id"] = account_id

    if not merchant_code:
        base["error"] = "飞书商品编码为空"
        return base

    try:
        listed_check = check_merchant_code_already_on_sale(
            account_id=account_id,
            merchant_code=merchant_code,
        )
        if listed_check.get("checked") and listed_check.get("listed"):
            base.update(
                ok=True,
                skipped=True,
                reason="already_on_sale",
                pdd_product_id=str(listed_check.get("pdd_product_id") or ""),
                list_status=str(listed_check.get("list_status") or ""),
            )
            logger.info(
                "cycle relist skip already listed record_id=%s merchant_code=%s account=%s pdd_product_id=%s",
                record_id,
                merchant_code,
                account_id,
                base.get("pdd_product_id") or "",
            )
            return base
    except Exception as exc:
        logger.warning(
            "cycle relist precheck goods list failed record_id=%s merchant_code=%s account=%s error=%s",
            record_id,
            merchant_code,
            account_id,
            exc,
        )

    if not skip_claim:
        claim_result = try_claim_cycle_relist(
            record_id,
            merchant_code=merchant_code,
            account_name=account_name,
            account_id=account_id,
            config=cfg,
            watch=watch_cfg,
        )
        base["claim"] = claim_result.to_dict()
        if not claim_result.claimed:
            if claim_result.reason == "redis_locked":
                base.update(ok=True, skipped=True, reason="already_claimed")
                return base
            if not claim_result.ok:
                base["error"] = claim_result.error or "占用失败"
                return base

    product_codes = [merchant_code]

    activity_ids = list(watch_cfg.pipeline_activity_ids or [])
    if not activity_ids:
        activity_ids = resolve_default_pipeline_activity_ids(cfg)

    try:
        pipeline = start_integrated_pipeline(
            account_id=account_id,
            product_codes=[merchant_code],
            activity_ids=activity_ids,
            category_keyword=str(watch_cfg.pipeline_category_keyword or "玩偶"),
            auto_promotion=bool(watch_cfg.pipeline_auto_promotion),
            continue_after_limited_time_failure=bool(
                watch_cfg.pipeline_continue_after_limited_time_failure
            ),
            continue_after_activity_failure=bool(
                watch_cfg.pipeline_continue_after_activity_failure
            ),
            activity_delay_hours=float(watch_cfg.pipeline_activity_delay_hours),
            demo_mode=bool(watch_cfg.pipeline_demo_mode),
            slot_alignment_test=bool(watch_cfg.pipeline_slot_alignment_test),
            material_source=str(watch_cfg.pipeline_material_source or "minio"),
            listing_input_mode="cycle_relist",
        )
    except Exception as exc:
        logger.exception(
            "cycle relist pipeline start failed record_id=%s merchant_code=%s",
            record_id,
            merchant_code,
        )
        base["error"] = str(exc)
        return base

    pipeline_id = str(pipeline.get("pipeline_id") or "").strip()
    if pipeline_id:
        try:
            update_integrated_pipeline(
                pipeline_id,
                meta_patch={
                    "cycle_relist_feishu_record_id": record_id,
                    "cycle_relist_merchant_code": merchant_code,
                    "cycle_relist_account_name": account_name,
                    "cycle_relist_account_id": account_id,
                    "cycle_relist_source": "failure_log_watch",
                },
            )
        except Exception:
            logger.exception(
                "patch pipeline cycle relist meta failed pipeline_id=%s record_id=%s",
                pipeline_id,
                record_id,
            )

    logger.info(
        "cycle relist pipeline started record_id=%s pipeline_id=%s account=%s products=%s",
        record_id,
        pipeline_id,
        account_id,
        product_codes,
    )
    base.update(
        ok=True,
        pipeline_id=pipeline_id,
        product_codes=list(pipeline.get("product_codes") or product_codes),
        account_id=account_id,
        reason="pipeline_started",
        report_platform=report_platform,
    )
    try:
        from pdd_agent.api.services.daily_cycle_relist_service import (
            record_cycle_relist_pipeline_started,
        )

        record_cycle_relist_pipeline_started(base, trigger_source=trigger_source)
    except Exception:
        logger.warning(
            "record daily cycle relist failed pipeline_id=%s record_id=%s",
            pipeline_id,
            record_id,
            exc_info=True,
        )
    return base
