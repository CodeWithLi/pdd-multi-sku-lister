"""
整合链路 — 套图上架结果索引与跳过结果合并。

统一处理：
- listing_label 两段式（BD757A/第一套图）与三段式 selector（BD757/第一套图/BD757A）互查
- 笔袋视图跳过（platform_not_applicable）写入 run results，并与平台去重跳过合并
"""

from __future__ import annotations

from typing import Any

from pdd_agent.integrations.feishu.listing_feishu_platform_guard import PLATFORM_SKIP_REASON

PLATFORM_NOT_APPLICABLE_REASON = "platform_not_applicable"
PLATFORM_SKIP_DEDUPE_REASON = "platform_skip_dedupe"

_SKIP_REASON_CODES = frozenset(
    {
        PLATFORM_NOT_APPLICABLE_REASON,
        PLATFORM_SKIP_DEDUPE_REASON,
        "skipped_already_listed",
    }
)


def canonical_listing_unit_label(text: str) -> str:
    """将 selector / listing_label 规范为 product_code/image_set（与链路选择器一致）。"""
    from pdd_agent.api.services.pipeline_service import _selector_to_listing_label

    return _selector_to_listing_label(str(text or "").strip())


def listing_unit_label_aliases(text: str) -> list[str]:
    """同一套图单元在 results / selectors 中可能出现的全部键。"""
    raw = str(text or "").strip()
    if not raw:
        return []

    aliases: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        key = str(value or "").strip()
        if key and key not in seen:
            seen.add(key)
            aliases.append(key)

    _add(raw)
    canonical = canonical_listing_unit_label(raw)
    _add(canonical)

    parts = [part.strip() for part in raw.split("/") if part.strip()]
    if len(parts) >= 3:
        family, image_set, product_code = parts[0], parts[1], parts[-1]
        _add(f"{product_code}/{image_set}")
        _add(f"{family}/{image_set}/{product_code}")
    elif len(parts) == 2:
        _add(f"{parts[0]}/{parts[1]}")

    return aliases


def index_listing_result_items(items: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """按 canonical 与别名索引上架结果项；同键后写覆盖先写。"""
    indexed: dict[str, dict[str, Any]] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("listing_label") or item.get("selector") or "").strip()
        if not label:
            continue
        payload = dict(item)
        if not str(payload.get("listing_label") or "").strip():
            payload["listing_label"] = canonical_listing_unit_label(label)
        for alias in listing_unit_label_aliases(label):
            indexed[alias] = payload
    return indexed


def merge_listing_result_indexes(*indexes: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """合并多个结果索引；后写覆盖先写。"""
    merged: dict[str, dict[str, Any]] = {}
    for index in indexes:
        if not index:
            continue
        merged.update(index)
    return merged


def resolve_listing_result_item(
    index: dict[str, dict[str, Any]],
    selector_or_label: str,
) -> dict[str, Any] | None:
    """按 selector 或 listing_label 在索引中查找上架结果。"""
    for alias in listing_unit_label_aliases(selector_or_label):
        item = index.get(alias)
        if isinstance(item, dict):
            return item
    return None


def classify_listing_unit_pipeline_status(item: dict[str, Any]) -> tuple[str, str]:
    """
    将单条上架结果映射为整合链路套图展示状态。

    返回 (status, reason_code)，status 对应 LISTING_UNIT_STATUS_LABELS 的键。
    """
    item_status = str(item.get("status") or "").strip().lower()
    item_reason = str(item.get("reason") or item.get("reason_code") or "").strip()
    product_id = str(item.get("pdd_product_id") or "").strip()

    if item_status in {"success", "listed"} and bool(product_id or item_status == "listed"):
        return "success", ""
    if item_status == "skipped" or item_reason in _SKIP_REASON_CODES:
        reason_code = item_reason or PLATFORM_SKIP_DEDUPE_REASON
        return "platform_skip_dedupe", reason_code
    return "failed", item_reason or "listing_failed"


def build_bag_view_skip_result_item(
    *,
    selector: str,
    folder: str,
) -> dict[str, Any]:
    """构造笔袋视图不适用跳过结果（使用 canonical listing_label）。"""
    selector_text = str(selector or "").strip()
    folder_text = str(folder or "").strip()
    return {
        "status": "skipped",
        "reason": PLATFORM_NOT_APPLICABLE_REASON,
        "reason_code": PLATFORM_NOT_APPLICABLE_REASON,
        "listing_label": canonical_listing_unit_label(selector_text),
        "selector": selector_text,
        "platform_listing_code": folder_text,
        "error": PLATFORM_SKIP_REASON,
    }


def build_bag_view_skip_result_items(
    *,
    missing_selectors: list[str],
    folder_by_selector: dict[str, str],
) -> list[dict[str, Any]]:
    """批量构造笔袋视图跳过结果。"""
    items: list[dict[str, Any]] = []
    for selector in missing_selectors:
        text = str(selector or "").strip()
        if not text:
            continue
        folder = str(folder_by_selector.get(text) or "").strip()
        items.append(build_bag_view_skip_result_item(selector=text, folder=folder))
    return items


def merge_skip_results_into_listing_payload(
    payload: dict[str, Any] | None,
    *,
    dedupe_skipped_results: list[dict[str, Any]] | None = None,
    bag_view_skipped_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    将平台去重 / 笔袋视图跳过结果并入上架 graph 返回体。

    按 canonical listing_label 去重，优先保留 graph 内已有结果。
    """
    base = dict(payload or {})
    graph_results = [dict(item) for item in (base.get("results") or []) if isinstance(item, dict)]
    graph_index = index_listing_result_items(graph_results)

    merged_results = list(graph_results)
    for group in (dedupe_skipped_results, bag_view_skipped_results):
        for item in group or []:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            label = str(
                normalized.get("listing_label")
                or normalized.get("selector")
                or ""
            ).strip()
            if not label:
                continue
            canonical = canonical_listing_unit_label(label)
            normalized["listing_label"] = canonical
            if resolve_listing_result_item(graph_index, canonical):
                continue
            merged_results.append(normalized)
            for alias in listing_unit_label_aliases(canonical):
                graph_index[alias] = normalized

    base["results"] = merged_results
    if dedupe_skipped_results:
        base["platform_skip_dedupe"] = True
    if bag_view_skipped_results:
        base["platform_bag_view_skip"] = True
    return base


def compose_all_skipped_listing_run_result(
    *,
    dedupe_skipped_results: list[dict[str, Any]] | None = None,
    bag_view_skipped_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """笔袋视图整批不适用、无剩余 codes 可跑时，生成仅含跳过项的 run result。"""
    return merge_skip_results_into_listing_payload(
        {"results": [], "errors": []},
        dedupe_skipped_results=dedupe_skipped_results,
        bag_view_skipped_results=bag_view_skipped_results,
    )


def listing_result_item_labels(items: list[dict[str, Any]] | None) -> list[str]:
    """提取 run finish 用的 listing_labels（canonical，去重保序）。"""
    labels: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        label = canonical_listing_unit_label(
            str(item.get("listing_label") or item.get("selector") or "")
        )
        if label and label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def build_listing_result_item_from_pipeline_skip_record(record: dict[str, Any]) -> dict[str, Any]:
    """将整合链路跳过明细表记录转为上架结果项（供状态面板回填）。"""
    kind = str(record.get("skip_kind") or "").strip()
    selector = str(record.get("product_selector") or "").strip()
    label = str(record.get("listing_label") or selector).strip()
    if kind == "platform_skip_dedupe":
        reason = PLATFORM_SKIP_DEDUPE_REASON
    elif kind == "bag_view_missing":
        reason = PLATFORM_NOT_APPLICABLE_REASON
    else:
        reason = kind or PLATFORM_SKIP_DEDUPE_REASON
    return {
        "status": "skipped",
        "reason": reason,
        "reason_code": reason,
        "listing_label": canonical_listing_unit_label(label or selector),
        "selector": selector,
        "platform_listing_code": str(record.get("merchant_code") or "").strip(),
        "error": str(record.get("message") or "").strip(),
    }


def index_pipeline_listing_skip_records(items: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """按跳过明细表构建结果索引（run 结果未落库时的兜底）。"""
    return index_listing_result_items(
        [
            build_listing_result_item_from_pipeline_skip_record(item)
            for item in (items or [])
            if isinstance(item, dict)
        ]
    )


def load_pipeline_listing_skip_result_index(pipeline_id: str) -> dict[str, dict[str, Any]]:
    """读取指定链路的跳过明细并索引为套图结果。"""
    pid = str(pipeline_id or "").strip()
    if not pid:
        return {}
    try:
        from pdd_agent.api.services.pipeline_listing_skip_record import get_pipeline_listing_skip_summary

        summary = get_pipeline_listing_skip_summary(pid)
        return index_pipeline_listing_skip_records(summary.get("items") or [])
    except Exception:
        return {}
