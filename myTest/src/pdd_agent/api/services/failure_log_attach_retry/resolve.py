"""失败日志挂回原链路 — 定位原链路批次商品目标。"""

from __future__ import annotations

from typing import Any

from pdd_agent.integrations.feishu.listing_feishu_catalog import codes_match, normalize_listing_code


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _selector_tail_code(selector: str) -> str:
    parts = [p.strip() for p in _norm(selector).split("/") if p.strip()]
    return parts[-1] if parts else ""


def merchant_code_matches_stage_row(merchant_code: str, item: dict[str, Any]) -> bool:
    code = _norm(merchant_code)
    if not code:
        return False
    target = normalize_listing_code(code) or code
    candidates = [
        _norm(item.get("product_selector")),
        _norm(item.get("listing_label")),
        _selector_tail_code(_norm(item.get("product_selector"))),
        _selector_tail_code(_norm(item.get("listing_label"))),
        _norm(item.get("pdd_product_id")),
    ]
    for raw in candidates:
        if not raw:
            continue
        if raw == code or normalize_listing_code(raw) == target:
            return True
        if codes_match(target, raw) or codes_match(target, normalize_listing_code(raw)):
            return True
        if raw.endswith(f"/{code}") or raw.endswith(f"/{target}"):
            return True
    return False


def resolve_attach_targets(
    *,
    pipeline_id: str,
    merchant_code: str,
    listing_selectors: list[str] | None = None,
) -> dict[str, Any]:
    """
    在原链路 batch product stages 中解析失败日志商品对应的行。

    返回 targets: [{batch_index, product_selector, pdd_product_id, mapping_id, listing_status, ...}]
    """
    from pdd_agent.api.services.pipeline_batch_product_stage_tracker import (
        STAGE_FAILED,
        STAGE_PENDING,
        STAGE_SUCCESS,
        list_pipeline_batch_product_stages,
    )

    pipeline_id = _norm(pipeline_id)
    merchant_code = _norm(merchant_code)
    stages = list_pipeline_batch_product_stages(pipeline_id=pipeline_id)
    matched = [item for item in stages if merchant_code_matches_stage_row(merchant_code, item)]

    if not matched and listing_selectors:
        wanted = {_norm(x) for x in listing_selectors if _norm(x)}
        matched = [
            item
            for item in stages
            if _norm(item.get("product_selector")) in wanted
            or _norm(item.get("listing_label")) in wanted
        ]

    # 优先失败/待处理，再其它
    def _rank(item: dict[str, Any]) -> tuple[int, int]:
        listing = _norm(item.get("listing_status"))
        lt = _norm(item.get("limited_time_status"))
        score = 3
        if listing == STAGE_FAILED or listing == STAGE_PENDING:
            score = 0
        elif listing == STAGE_SUCCESS and lt in {STAGE_FAILED, STAGE_PENDING, ""}:
            score = 1
        return (score, int(item.get("batch_index") or 0))

    matched = sorted(matched, key=_rank)
    selectors = list(
        dict.fromkeys(_norm(item.get("product_selector")) for item in matched if _norm(item.get("product_selector")))
    )
    if not selectors and listing_selectors:
        selectors = [_norm(x) for x in listing_selectors if _norm(x)]

    return {
        "pipeline_id": pipeline_id,
        "merchant_code": merchant_code,
        "targets": matched,
        "selectors": selectors,
        "batch_indices": sorted(
            {int(item.get("batch_index") or 0) for item in matched if item.get("batch_index") is not None}
        ),
        "matched_count": len(matched),
    }
