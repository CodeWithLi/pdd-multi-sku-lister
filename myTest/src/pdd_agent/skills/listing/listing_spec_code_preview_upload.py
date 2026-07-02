"""按规格编码定位价格表行并上传预览图。

文字字段（含规格编码）填完后，不再依赖「款式名 + 尺寸名」或行号索引上传预览图，
而是在页面表格中查找规格编码输入框与目标编码一致的行，再上传对应图片。

典型素材命名（与规格编码一致）::

    BD062A.jpg
    BD062A+YKL004L.jpg
    BD062A+YKL020A.jpg
    BD062A+YKL004L+YKL020A+YKL007P.jpg
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pdd_agent.skills.listing.pdd_page_image_errors import (
    PddImageUploadRejected,
    raise_if_pdd_image_upload_rejected,
)

_SPEC_CODE_ATTR = "data-pdd-spec-code"
_PREVIEW_POST_INPUT_WAIT = 1.2
_PREVIEW_VERIFY_TIMEOUT = 20.0
_PREVIEW_VERIFY_INTERVAL = 0.45
_MAX_UPLOAD_RETRIES = 3

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class SpecCodePreviewItem:
    """单个「规格编码 → 预览图」上传任务。"""

    spec_code: str
    image_path: Path
    combo_folder: str = ""
    style_name: str = ""
    model_name: str = ""

    @property
    def label(self) -> str:
        if self.style_name and self.model_name:
            return f"{self.style_name} / {self.model_name}"
        return self.spec_code


@dataclass
class SpecCodePreviewUploadResult:
    uploaded: int = 0
    verified: int = 0
    need_upload: int = 0
    missing_codes: list[str] = field(default_factory=list)
    failed_items: list[dict[str, str]] = field(default_factory=list)


class _PageLike(Protocol):
    def run_js(self, script: str, *args) -> Any: ...
    def ele(self, locator: str, timeout: float = ...) -> Any: ...


def normalize_spec_code(code: str) -> str:
    """规格编码比对键：去空白、统一大写（与页面填表校验一致）。"""
    text = _WHITESPACE_RE.sub("", str(code or "").strip())
    return text.upper()


def build_spec_code_preview_items(skus: list[Any]) -> list[SpecCodePreviewItem]:
    """从 SKU 列表构建上传计划；规格编码优先 combo_folder，否则用预览图文件名。"""
    items: list[SpecCodePreviewItem] = []
    seen: set[str] = set()
    for sku in skus or []:
        preview = getattr(sku, "preview_image", None)
        if not preview:
            continue
        combo_folder = str(getattr(sku, "combo_folder", "") or "").strip()
        stem = Path(str(preview)).stem.strip()
        spec_code = combo_folder or stem
        if not spec_code:
            continue
        key = normalize_spec_code(spec_code)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            SpecCodePreviewItem(
                spec_code=spec_code,
                image_path=Path(preview),
                combo_folder=combo_folder,
                style_name=str(getattr(sku, "style_name", "") or ""),
                model_name=str(getattr(sku, "model_name", "") or ""),
            )
        )
    return items


_JS_ROW_SCAN_HELPERS = """
function rowInputs(tr) {
    const inputs = [];
    for (const td of tr.querySelectorAll('td')) {
        if (td.querySelector('input[type="file"]')) continue;
        for (const inp of td.querySelectorAll('input')) {
            const t = (inp.type || '').toLowerCase();
            if (!['file','hidden','checkbox','radio','button','submit'].includes(t)) {
                inputs.push(inp);
                break;
            }
        }
    }
    return inputs;
}

function isSkuDataRow(tr) {
    if (!tr || !tr.querySelector('.sku-preview-cell, td[class*="sku-preview"]')) return false;
    let n = 0;
    for (const inp of tr.querySelectorAll('input')) {
        const t = (inp.type || '').toLowerCase();
        if (!['file','hidden','checkbox','radio','button','submit'].includes(t)) n++;
    }
    return n >= 3;
}

function collectSkuDataRows() {
    const out = [];
    const sels = [
        '.sku-table tr[data-testid="beast-core-table-body-tr"]',
        '.sku-list tr[data-testid="beast-core-table-body-tr"]',
        'tr[data-pdd-sku-row]',
    ];
    const seen = new Set();
    for (const sel of sels) {
        for (const tr of document.querySelectorAll(sel)) {
            if (!isSkuDataRow(tr) || seen.has(tr)) continue;
            seen.add(tr);
            out.push(tr);
        }
    }
    return out;
}

function normFieldText(text) {
    return String(text || '').replace(/\\s+/g, ' ').trim();
}

function normSpecCode(code) {
    return normFieldText(code).replace(/\\s+/g, '').toUpperCase();
}

function readRowSpecCode(tr) {
    const inputs = rowInputs(tr);
    if (inputs.length >= 4) return normFieldText(inputs[3].value);
    return '';
}

function previewCellNeedsUpload(cell) {
    if (!cell) return true;
    const text = (cell.innerText || cell.textContent || '').replace(/\\s+/g, '');
    return text.includes('请上传预览图') || text.includes('上传预览图');
}

function isPreviewCellUploaded(cell) {
    if (!cell || previewCellNeedsUpload(cell)) return false;
    if (cell.querySelector('[class*="delete"], [class*="close"], [class*="remove"], [class*="del"]'))
        return true;
    for (const img of cell.querySelectorAll('img')) {
        const r = img.getBoundingClientRect();
        if (r.width >= 20 && r.height >= 20) return true;
    }
    return false;
}

function getPreviewCell(tr) {
    return tr?.querySelector('.sku-preview-cell, td[class*="sku-preview"]') || null;
}

function getSkuScrollTargets() {
    const targets = [];
    const seen = new Set();
    function isScrollable(el) {
        if (!el) return false;
        const st = getComputedStyle(el);
        const oy = st.overflowY || st.overflow;
        return (oy === 'auto' || oy === 'scroll' || oy === 'overlay')
            && el.scrollHeight > el.clientHeight + 4;
    }
    function add(el) {
        if (!el || seen.has(el) || !isScrollable(el)) return;
        seen.add(el);
        targets.push(el);
    }
    const sample = document.querySelector(
        '.sku-table tr[data-testid="beast-core-table-body-tr"], '
        + '.sku-list tr[data-testid="beast-core-table-body-tr"]'
    );
    if (sample) {
        let el = sample.parentElement;
        while (el && el !== document.documentElement) {
            add(el);
            el = el.parentElement;
        }
    }
    for (const sel of ['.sku-table .ant-table-body', '.sku-list .ant-table-body', '.sku-table', '.sku-list']) {
        for (const el of document.querySelectorAll(sel)) add(el);
    }
    return targets;
}

function fireScroll(el) {
    if (!el) return;
    el.dispatchEvent(new Event('scroll', { bubbles: true }));
}

function scrollTableStep(stepPx) {
    const targets = getSkuScrollTargets();
    if (!targets.length) {
        window.scrollBy(0, stepPx);
        return true;
    }
    let moved = false;
    for (const t of targets) {
        const before = t.scrollTop;
        t.scrollTop = Math.min(t.scrollHeight, before + stepPx);
        fireScroll(t);
        if (t.scrollTop !== before) moved = true;
    }
    return moved;
}

function scrollTableToTop() {
    for (const t of getSkuScrollTargets()) {
        t.scrollTop = 0;
        fireScroll(t);
    }
}

function scanSpecCodeMap(map) {
    let added = 0;
    for (const tr of collectSkuDataRows()) {
        const code = readRowSpecCode(tr);
        if (!code) continue;
        const key = normSpecCode(code);
        if (map[key]) continue;
        map[key] = code;
        tr.setAttribute('data-pdd-spec-code', code);
        added++;
    }
    return added;
}
"""

_BUILD_SPEC_CODE_MAP_JS = (
    _JS_ROW_SCAN_HELPERS
    + """
const expected = parseInt(arguments[0], 10) || 0;
const map = {};
scrollTableToTop();
scanSpecCodeMap(map);
const stepPx = 72;
for (let step = 0; step < 160; step++) {
    if (expected > 0 && Object.keys(map).length >= expected) break;
    const moved = scrollTableStep(stepPx);
    scanSpecCodeMap(map);
    if (!moved) break;
}
for (const t of getSkuScrollTargets()) {
    t.scrollTop = t.scrollHeight;
    fireScroll(t);
}
scanSpecCodeMap(map);
scrollTableToTop();
return JSON.stringify(map);
"""
)

_FIND_ROW_BY_SPEC_CODE_JS = (
    _JS_ROW_SCAN_HELPERS
    + """
const target = normSpecCode(arguments[0] || '');
if (!target) return JSON.stringify({found: false});

function tryFind() {
    for (const tr of collectSkuDataRows()) {
        const code = readRowSpecCode(tr);
        if (!code) continue;
        if (normSpecCode(code) !== target) continue;
        tr.setAttribute('data-pdd-spec-code', code);
        try {
            tr.scrollIntoView({block: 'center', behavior: 'instant'});
        } catch (e) {
            tr.scrollIntoView({block: 'center'});
        }
        const cell = getPreviewCell(tr);
        return {
            found: true,
            code: code,
            uploaded: isPreviewCellUploaded(cell),
        };
    }
    return null;
}

scrollTableToTop();
let hit = tryFind();
if (hit) return JSON.stringify(hit);

for (let step = 0; step < 160; step++) {
    const moved = scrollTableStep(72);
    hit = tryFind();
    if (hit) return JSON.stringify(hit);
    if (!moved) break;
}

for (const t of getSkuScrollTargets()) {
    t.scrollTop = t.scrollHeight;
    fireScroll(t);
}
hit = tryFind();
return JSON.stringify(hit || {found: false});
"""
)

_UPLOAD_PREVIEW_IN_SPEC_ROW_JS = (
    _JS_ROW_SCAN_HELPERS
    + """
const target = normSpecCode(arguments[0] || '');
if (!target) return JSON.stringify({ready: false, reason: 'empty_code'});

for (const tr of collectSkuDataRows()) {
    const code = readRowSpecCode(tr);
    if (!code || normSpecCode(code) !== target) continue;
    tr.setAttribute('data-pdd-spec-code', code);
    try {
        tr.scrollIntoView({block: 'center', behavior: 'instant'});
    } catch (e) {
        tr.scrollIntoView({block: 'center'});
    }
    const cell = getPreviewCell(tr);
    if (!cell) return JSON.stringify({ready: false, reason: 'no_preview_cell'});
    if (isPreviewCellUploaded(cell)) {
        return JSON.stringify({ready: false, uploaded: true, code: code});
    }
    let inp = cell.querySelector('input[type="file"]');
    if (!inp) {
        const btn = cell.querySelector('[class*="upload"], [class*="Upload"], .ant-upload, svg');
        (btn || cell).click();
    }
    inp = cell.querySelector('input[type="file"]');
    if (!inp) {
        for (const i of tr.querySelectorAll('input')) {
            const t = (i.type || '').toLowerCase();
            if (t === 'file' || (i.accept || '').includes('image')) {
                inp = i;
                break;
            }
        }
    }
    if (!inp) return JSON.stringify({ready: false, reason: 'no_file_input', code: code});
    inp.setAttribute('data-pdd-preview-spec-code', code);
    return JSON.stringify({ready: true, code: code});
}
return JSON.stringify({ready: false, reason: 'row_not_found'});
"""
)

_CHECK_PREVIEW_BY_SPEC_CODE_JS = (
    _JS_ROW_SCAN_HELPERS
    + """
const target = normSpecCode(arguments[0] || '');
if (!target) return false;
for (const tr of collectSkuDataRows()) {
    const code = readRowSpecCode(tr);
    if (!code || normSpecCode(code) !== target) continue;
    return isPreviewCellUploaded(getPreviewCell(tr));
}
return false;
"""
)


def _parse_js_json(raw: Any, default: dict | None = None) -> dict:
    if default is None:
        default = {}
    if isinstance(raw, dict):
        return raw
    if not raw:
        return default
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return default
    return parsed if isinstance(parsed, dict) else default


def build_page_spec_code_map(page: _PageLike, *, expected: int = 0) -> dict[str, str]:
    """滚动价格表，读取已填规格编码 → 页面原始编码文本。"""
    try:
        raw = page.run_js(_BUILD_SPEC_CODE_MAP_JS, str(max(0, expected))) or "{}"
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in data.items():
        text = str(value or "").strip()
        if text:
            out[normalize_spec_code(key)] = text
    return out


def _resolve_spec_row_file_input(page: _PageLike, spec_code: str):
    info = _parse_js_json(page.run_js(_UPLOAD_PREVIEW_IN_SPEC_ROW_JS, spec_code))
    if info.get("uploaded"):
        return None, info
    if not info.get("ready"):
        return None, info
    code = str(info.get("code") or spec_code)
    upload_input = page.ele(
        f"css:input[data-pdd-preview-spec-code='{code}']",
        timeout=0.5,
    )
    if not upload_input:
        upload_input = page.ele(
            f"css:tr[{_SPEC_CODE_ATTR}='{code}'] input[type='file']",
            timeout=0.5,
        )
    return upload_input, info


def _wait_preview_uploaded_by_spec_code(page: _PageLike, spec_code: str) -> bool:
    deadline = time.perf_counter() + _PREVIEW_VERIFY_TIMEOUT
    while time.perf_counter() < deadline:
        try:
            if page.run_js(_CHECK_PREVIEW_BY_SPEC_CODE_JS, spec_code):
                return True
        except Exception:
            pass
        time.sleep(_PREVIEW_VERIFY_INTERVAL)
    return False


def upload_preview_for_spec_code(
    page: _PageLike,
    account_id: str,
    item: SpecCodePreviewItem,
    *,
    max_retries: int = _MAX_UPLOAD_RETRIES,
) -> bool:
    """在规格编码已写入的价格表行上传预览图。"""
    spec_code = item.spec_code
    image_path = str(item.image_path.resolve())
    label = item.label

    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            print(
                f"[{account_id}] 预览图重试 ({attempt}/{max_retries})："
                f"规格编码={spec_code}",
                flush=True,
            )
            time.sleep(0.4)

        find_info = _parse_js_json(page.run_js(_FIND_ROW_BY_SPEC_CODE_JS, spec_code))
        if find_info.get("uploaded"):
            print(f"[{account_id}] 预览图已存在，跳过 规格编码={spec_code}", flush=True)
            return True
        if not find_info.get("found"):
            print(
                f"[{account_id}] 未找到规格编码所在行：{spec_code} [{label}]",
                flush=True,
            )
            continue

        upload_input, prep_info = _resolve_spec_row_file_input(page, spec_code)
        if prep_info.get("uploaded"):
            return True
        if not upload_input:
            reason = str(prep_info.get("reason") or "no_input")
            print(
                f"[{account_id}] 规格编码行无上传框：{spec_code} ({reason})",
                flush=True,
            )
            continue

        try:
            upload_input.input(image_path)
        except Exception as exc:
            print(
                f"[{account_id}] 预览图文件选择失败 规格编码={spec_code}：{exc}",
                flush=True,
            )
            continue

        time.sleep(_PREVIEW_POST_INPUT_WAIT)
        raise_if_pdd_image_upload_rejected(
            page,
            account_id=account_id,
            label=label,
            image_kind="preview",
            sku_label=f"{spec_code} ({label})",
        )

        if _wait_preview_uploaded_by_spec_code(page, spec_code):
            print(
                f"[{account_id}] 已上传预览图 规格编码={spec_code} ← {item.image_path.name}",
                flush=True,
            )
            return True

        raise_if_pdd_image_upload_rejected(
            page,
            account_id=account_id,
            label=label,
            image_kind="preview",
            sku_label=f"{spec_code} ({label})",
        )

    return False


def upload_previews_by_spec_code(
    page: _PageLike,
    account_id: str,
    skus: list[Any],
    *,
    prepare_table: bool = True,
) -> SpecCodePreviewUploadResult:
    """
    在规格编码已填写完成后，按规格编码逐个上传预览图。

    Parameters
    ----------
    prepare_table:
        为 True 时调用 multi_spec_page 的表格滚动/标记逻辑（懒加载以避免循环引用）。
    """
    items = build_spec_code_preview_items(skus)
    result = SpecCodePreviewUploadResult(need_upload=len(items))
    if not items:
        return result

    if prepare_table:
        from pdd_agent.skills.listing.multi_spec_page import (
            _mark_preview_inputs,
            _scroll_sku_table_to_load,
            _stamp_global_row_indices,
        )

        _scroll_sku_table_to_load(page, len(items))
        style_names: list[str] = []
        size_names: list[str] = []
        try:
            first = skus[0]
            # 仅用于虚拟滚动预热；上传定位以规格编码为准。
            style_names = list(
                dict.fromkeys(
                    str(getattr(s, "style_name", "") or "")
                    for s in skus
                    if getattr(s, "style_name", None)
                )
            )
            size_names = list(
                dict.fromkeys(
                    str(getattr(s, "model_name", "") or "")
                    for s in skus
                    if getattr(s, "model_name", None)
                )
            )
        except Exception:
            pass
        if style_names and size_names:
            _stamp_global_row_indices(page, style_names, size_names)
        _mark_preview_inputs(page)

    page_map = build_page_spec_code_map(page, expected=len(items))
    print(
        f"[{account_id}] 按规格编码上传预览图：任务 {len(items)} 个，"
        f"页面已识别编码 {len(page_map)} 个",
        flush=True,
    )

    for item in items:
        key = normalize_spec_code(item.spec_code)
        if key not in page_map:
            result.missing_codes.append(item.spec_code)
            result.failed_items.append(
                {
                    "spec_code": item.spec_code,
                    "reason": "spec_code_not_on_page",
                }
            )
            print(
                f"[{account_id}] 页面未找到规格编码，跳过预览图：{item.spec_code}",
                flush=True,
            )
            continue

        print(
            f"[{account_id}] >>> 预览图 规格编码={item.spec_code} "
            f"← {item.image_path.name}",
            flush=True,
        )
        try:
            if upload_preview_for_spec_code(page, account_id, item):
                result.uploaded += 1
                if _wait_preview_uploaded_by_spec_code(page, item.spec_code):
                    result.verified += 1
            else:
                result.failed_items.append(
                    {
                        "spec_code": item.spec_code,
                        "reason": "upload_failed",
                    }
                )
        except PddImageUploadRejected:
            raise
        except Exception as exc:
            err = str(exc)
            if "连接已断开" in err or "disconnect" in err.lower():
                raise
            result.failed_items.append(
                {
                    "spec_code": item.spec_code,
                    "reason": "upload_exception",
                    "error": err[:200],
                }
            )
            print(
                f"[{account_id}] 预览图异常 规格编码={item.spec_code}：{err}",
                flush=True,
            )

    print(
        f"[{account_id}] 按规格编码预览图结果：上传 {result.uploaded}/{result.need_upload}，"
        f"校验 {result.verified}/{result.need_upload}",
        flush=True,
    )
    if result.missing_codes:
        print(
            f"[{account_id}] [警告] 页面未匹配到的规格编码："
            f"{', '.join(result.missing_codes[:8])}",
            flush=True,
        )
    return result
