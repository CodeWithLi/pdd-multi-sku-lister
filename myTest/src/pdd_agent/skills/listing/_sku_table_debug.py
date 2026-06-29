"""临时诊断日志：虚拟滚动规格表 / rowspan 解析。

确认问题修复稳定后，删除本文件，并移除 multi_spec_page.py 中
``from pdd_agent.skills.listing._sku_table_debug import ...`` 相关调用。
"""

from __future__ import annotations

import json
from typing import Any

# 一键关闭；后续整文件删除时可忽略此开关
ENABLED = True

TAG = "SKUDBG"


def enabled() -> bool:
    return ENABLED


def _fmt(value: Any) -> str:
    if isinstance(value, (list, dict)):
        text = json.dumps(value, ensure_ascii=False)
        if len(text) > 500:
            return f"{text[:500]}...(共{len(text)}字)"
        return text
    return str(value)


def log(account_id: str, phase: str, message: str, **fields: Any) -> None:
    if not ENABLED:
        return
    suffix = ""
    if fields:
        suffix = " | " + " ".join(f"{key}={_fmt(val)}" for key, val in fields.items())
    print(f"[{account_id}][{TAG}][{phase}] {message}{suffix}", flush=True)


def log_block_start(account_id: str, title: str) -> None:
    if not ENABLED:
        return
    print(f"[{account_id}][{TAG}] ===== {title} =====", flush=True)


def log_block_end(account_id: str, title: str) -> None:
    if not ENABLED:
        return
    print(f"[{account_id}][{TAG}] ===== END {title} =====", flush=True)


def log_snapshot(
    page,
    account_id: str,
    phase: str,
    snapshot_js: str,
    styles_json: str,
    sizes_json: str,
) -> dict[str, Any] | None:
    """执行页面快照 JS，输出可复制给 AI 的结构化块。"""
    if not ENABLED:
        return None
    try:
        raw = page.run_js(snapshot_js, styles_json, sizes_json) or "{}"
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict):
            log(account_id, phase, "snapshot_invalid_type", raw_type=type(data).__name__)
            return None
    except Exception as exc:
        log(account_id, phase, "snapshot_failed", error=str(exc))
        return None

    log_block_start(account_id, f"{phase}")
    _log_kv(account_id, phase, "expected", data.get("expected"))
    _log_kv(account_id, phase, "visibleDataRowCount", data.get("visibleDataRowCount"))
    _log_kv(account_id, phase, "collectedRowCount", data.get("collectedRowCount"))
    _log_kv(account_id, phase, "parsedSpecPairCount", data.get("parsedSpecPairCount"))
    _log_kv(account_id, phase, "mappedSpecPairCount", data.get("mappedSpecPairCount"))
    _log_kv(account_id, phase, "stampedAttrCount", data.get("stampedAttrCount"))
    _log_kv(account_id, phase, "domMarkedRowCount", data.get("domMarkedRowCount"))
    _log_kv(account_id, phase, "missingPairCount", data.get("missingPairCount"))
    _log_kv(account_id, phase, "scrollTargetCount", data.get("scrollTargetCount"))
    _log_kv(account_id, phase, "styleNames", data.get("styleNames"))
    _log_kv(account_id, phase, "sizeNames", data.get("sizeNames"))

    scroll_targets = data.get("scrollTargets") or []
    if scroll_targets:
        _log_kv(account_id, phase, "scrollTargets", scroll_targets)

    missing = data.get("missingPairs") or []
    if missing:
        _log_kv(account_id, phase, "missingPairs", missing)

    parsed_pairs = data.get("parsedPairs") or []
    if parsed_pairs:
        _log_kv(account_id, phase, "parsedPairs", parsed_pairs)

    map_entries = data.get("mapEntries") or []
    if map_entries:
        _log_kv(account_id, phase, "mapEntries", map_entries)

    collected_samples = (
        data.get("collectedRowTextSamples")
        or data.get("collectedSamples")
        or []
    )
    if collected_samples:
        _log_kv(account_id, phase, "collectedRowTextSamples", collected_samples)

    visible_samples = data.get("visibleRowTextSamples") or []
    if visible_samples:
        _log_kv(account_id, phase, "visibleRowTextSamples", visible_samples)

    unparsed = data.get("unparsedRowSamples") or []
    if unparsed:
        _log_kv(account_id, phase, "unparsedRowSamples", unparsed)

    dom_labels = data.get("domSpecLabels") or []
    if dom_labels:
        _log_kv(account_id, phase, "domSpecLabels", dom_labels)

    log_block_end(account_id, f"{phase}")
    return data


def log_diagnose(account_id: str, phase: str, info: dict[str, Any]) -> None:
    """填表诊断 JS 的结构化输出。"""
    if not ENABLED or not info:
        return
    log_block_start(account_id, f"{phase} DIAGNOSE")
    for key in (
        "tableRows",
        "markedRows",
        "specMarkedRows",
        "dataRows",
        "inputsInFirst",
    ):
        if key in info:
            _log_kv(account_id, phase, key, info.get(key))
    page_specs = info.get("pageSpecs") or []
    if page_specs:
        _log_kv(account_id, phase, "pageSpecRowCount", len(page_specs))
        _log_kv(account_id, phase, "pageSpecs", page_specs[:40])
        if len(page_specs) > 40:
            log(account_id, phase, "pageSpecs_truncated", remaining=len(page_specs) - 40)
    log_block_end(account_id, f"{phase} DIAGNOSE")


def log_spec_map(account_id: str, phase: str, rows: list[Any]) -> None:
    if not ENABLED:
        return
    log_block_start(account_id, f"{phase} SPEC_MAP")
    log(account_id, phase, "row_count", count=len(rows))
    for row in rows[:40]:
        if not isinstance(row, dict):
            continue
        log(
            account_id,
            phase,
            "spec_row",
            idx=int(row.get("idx", -1)) + 1,
            style=row.get("style", ""),
            size=row.get("size", ""),
        )
    if len(rows) > 40:
        log(account_id, phase, "spec_map_truncated", remaining=len(rows) - 40)
    log_block_end(account_id, f"{phase} SPEC_MAP")


def log_row_probe(
    account_id: str,
    phase: str,
    style: str,
    size: str,
    probe: dict[str, Any] | None,
) -> None:
    """单行填表失败时的页面探测结果。"""
    if not ENABLED:
        return
    if not probe:
        log(account_id, phase, "row_probe_failed", style=style, size=size)
        return
    log(
        account_id,
        phase,
        "row_probe",
        style=style,
        size=size,
        expectedIdx=probe.get("expectedIdx"),
        inStyleList=probe.get("inStyleList"),
        inSizeList=probe.get("inSizeList"),
        mapHasEntry=probe.get("mapHasEntry"),
        mapIdx=probe.get("mapIdx"),
        scrollFound=probe.get("scrollFound"),
        rowFound=probe.get("rowFound"),
        inputCount=probe.get("inputCount"),
        verifyFilled=probe.get("verifyFilled"),
        rowText=probe.get("rowText", ""),
    )


def log_fill_failures(account_id: str, phase: str, failed: list[dict]) -> None:
    if not ENABLED or not failed:
        return
    log_block_start(account_id, f"{phase} FAILURES ({len(failed)})")
    for item in failed[:40]:
        log(
            account_id,
            phase,
            "fill_failed",
            style=item.get("style", ""),
            size=item.get("size", ""),
            reason=item.get("reason", ""),
        )
    if len(failed) > 40:
        log(account_id, phase, "fill_failed_truncated", remaining=len(failed) - 40)
    log_block_end(account_id, f"{phase} FAILURES")


def log_fill_progress(
    account_id: str,
    phase: str,
    *,
    filled: int,
    total: int,
    failed_count: int = 0,
    extra: dict[str, Any] | None = None,
) -> None:
    if not ENABLED:
        return
    fields: dict[str, Any] = {
        "filled": filled,
        "total": total,
        "failed": failed_count,
    }
    if extra:
        fields.update(extra)
    log(account_id, phase, "fill_progress", **fields)


def _log_kv(account_id: str, phase: str, key: str, value: Any) -> None:
    log(account_id, phase, key, value=value)
