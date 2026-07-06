"""拼多多发布页「商品属性」搜索下拉框填写（独立封装，供 upload 引用）。"""

from __future__ import annotations

import json
import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.skills.listing.multi_spec_page import _safe_exc

LOG_TAG = "product_attrs"

NO_RESULT_PHRASES = frozenset(
    {
        "搜索无结果",
        "暂无数据",
        "无匹配结果",
        "无结果",
        "未找到相关",
    }
)

SKIP_OPTION_PHRASES = ("更多品牌请搜索", "更多请搜索")

REASON_CODES = {
    "section_not_ready": "ATTR_SECTION_NOT_READY",
    "not_found": "ATTR_INPUT_NOT_FOUND",
    "click_failed": "ATTR_INPUT_CLICK_FAILED",
    "type_failed": "ATTR_TYPE_FAILED",
    "timeout": "ATTR_DROPDOWN_TIMEOUT",
    "option_not_found": "ATTR_OPTION_NOT_FOUND",
    "click_failed_option": "ATTR_OPTION_CLICK_FAILED",
    "empty_label_or_value": "ATTR_EMPTY_CONFIG",
    "no_attributes_configured": "ATTR_NO_CONFIG",
}

REASON_HINTS = {
    "ATTR_SECTION_NOT_READY": "商品属性区尚未渲染完成，请确认标题已填完且页面在「基本信息」详情页",
    "ATTR_INPUT_NOT_FOUND": "页面上找不到该属性输入框，请核对标签名或 DOM 是否变化",
    "ATTR_INPUT_CLICK_FAILED": "找到输入框但点击失败，可能被遮罩层挡住",
    "ATTR_TYPE_FAILED": "输入框无法键入搜索词",
    "ATTR_DROPDOWN_TIMEOUT": "已输入搜索词但下拉选项长时间未出现（可能网络慢）",
    "ATTR_OPTION_NOT_FOUND": "下拉已出现但没有匹配选项，请检查配置值是否与拼多多选项一致",
    "ATTR_OPTION_CLICK_FAILED": "找到选项但点击失败",
}

DROPDOWN_OPTION_SELECTORS = (
    'ul[role="listbox"] li[role="option"]',
    '[data-testid="beast-core-portal-main"] li[role="option"]',
    '[data-testid="beast-core-portal-main"] [data-testid="beast-core-select-option"]',
    '[class*="ST_dropdownPanel"] li[role="option"]',
    '[class*="dropdownPanel"] li[role="option"]',
    ".ant-select-item-option-content",
    ".ant-select-item-option",
    '[data-testid="beast-core-select-option"]',
)

_SCROLL_PRODUCT_ATTRIBUTES_JS = """
for (const marker of ['商品属性', '填写率']) {
  for (const el of document.querySelectorAll('div,span,label,h3,h4')) {
    const t = (el.textContent || '').trim();
    if (!t.includes(marker) || t.length > 40) continue;
    try {
      el.scrollIntoView({ block: 'center', behavior: 'instant' });
    } catch (e) {}
    return { ok: true, marker };
  }
}
return { ok: false };
"""

# PDD 分支 C：属性字段在 div#property-list-xxx / PropertyItemItem 内（双列 grid）
_PROPERTY_FIELD_JS_CORE = """
const norm = (s) => String(s || '').replace(/\\s+/g, '');

const KNOWN_LABELS = [
  '品牌', '重要材质', '特点', '适用性别', '适用年龄段', '风格', '闭合方式',
  '是否透明', '是否有夹层', '是否防水', '流行元素', '适用人群', '适用场景',
  '产品类型', '图案', '包装方式',
];

const RIGHT_COLUMN_LABELS = new Set([
  '重要材质', '适用性别', '风格', '是否透明', '是否防水', '适用人群', '产品类型', '包装方式',
]);

const PROPERTY_CELL_SELECTORS = [
  'div[id^="property-list-"]',
  '[class*="property-list"]',
  '[class*="PropertyItemItem"]',
];

const INPUT_SELECTORS = [
  '[data-testid="beast-core-select-html-input"]',
  'input[type="text"]',
  'input[type="search"]',
  '[class*="IPT_input"] input',
  '[class*="IPT_input"]',
];

const isNoiseLine = (line) => {
  const t = norm(line);
  if (!t) return true;
  if (t === '商品属性' || t === '填写率' || t === '请选择') return true;
  if (t.includes('点击申请')) return true;
  if (t.startsWith('未找到')) return true;
  if (t.includes('请输入') && t.includes('搜索')) return true;
  return false;
};

const findInputInCell = (cell) => {
  if (!(cell instanceof Element)) return null;
  for (const sel of INPUT_SELECTORS) {
    const el = cell.querySelector(sel);
    if (el instanceof HTMLInputElement && el.type !== 'hidden' && el.type !== 'file') return el;
  }
  return null;
};

const countPropertyCells = (root) => {
  if (!(root instanceof Element)) return 0;
  const seen = new Set();
  let count = 0;
  for (const sel of PROPERTY_CELL_SELECTORS) {
    for (const cell of root.querySelectorAll(sel)) {
      if (seen.has(cell)) continue;
      if (!findInputInCell(cell)) continue;
      seen.add(cell);
      count += 1;
    }
  }
  return count;
};

const labelFromPropertyList = (cell) => {
  if (!(cell instanceof Element)) return '';
  const input = findInputInCell(cell);
  const inputVal = norm(input ? input.value : '');

  const labelSelectors = [
    '[class*="property-name"]',
    '[class*="PropertyName"]',
    '[class*="property_label"]',
    '[class*="form-label"]',
    '[class*="FormItem_label"]',
    '[class*="label"]',
    '[class*="Label"]',
    '[class*="title"]',
  ];
  for (const sel of labelSelectors) {
    for (const el of cell.querySelectorAll(sel)) {
      if (input && (el === input || el.contains(input))) continue;
      const raw = String(el.textContent || '').trim().replace(/[*:：]/g, '');
      const t = norm(raw);
      if (!t || isNoiseLine(raw)) continue;
      if (t === inputVal) continue;
      if (t.includes('重要') && String(cell.innerText || '').includes('材质')) return '重要材质';
      if (t.length >= 2 && t.length <= 16) return t;
    }
  }

  for (const child of cell.children) {
    if (input && child.contains(input)) continue;
    const raw = String(child.textContent || '').trim().replace(/[*:：]/g, '');
    const t = norm(raw);
    if (!t || isNoiseLine(raw)) continue;
    if (t === inputVal) continue;
    if (t.includes('重要') && String(cell.innerText || '').includes('材质')) return '重要材质';
    if (t.length >= 2 && t.length <= 16) return t;
  }

  const fullText = String(cell.innerText || '');
  for (const known of KNOWN_LABELS) {
    if (fullText.includes(known)) return known;
  }

  const lines = fullText.split('\\n').map((l) => l.trim()).filter(Boolean);
  for (const line of lines) {
    if (isNoiseLine(line)) continue;
    const t = norm(line.replace(/[*:：]/g, ''));
    if (!t || t === inputVal) continue;
    if (t.length >= 2 && t.length <= 16) return t;
  }
  return '';
};

const findPropertyScope = () => {
  let header = null;
  for (const el of document.querySelectorAll('div,span,section,label,h3,h4')) {
    const t = (el.textContent || '').trim();
    if (t === '商品属性') {
      header = el;
      break;
    }
  }
  if (!header) return { scope: document.body, headerBottom: 0 };

  let best = null;
  let bestListCount = Infinity;
  let node = header.parentElement;
  for (let i = 0; i < 20 && node; i++) {
    const count = countPropertyCells(node);
    if (count >= 8 && count < bestListCount) {
      best = node;
      bestListCount = count;
    }
    node = node.parentElement;
  }
  if (!best) {
    node = header.parentElement;
    for (let i = 0; i < 20 && node; i++) {
      if (countPropertyCells(node) >= 4) {
        best = node;
        break;
      }
      node = node.parentElement;
    }
  }
  const scope = best || document.body;
  const headerBottom = header.getBoundingClientRect().bottom || 0;
  return { scope, headerBottom };
};

const collectPropertyFields = (scopeInfo) => {
  const scope = scopeInfo.scope || document.body;
  const headerBottom = scopeInfo.headerBottom || 0;
  const seenInputs = new Set();
  const seenCells = new Set();
  const rows = [];

  const addRow = (cell, input) => {
    if (!input || seenInputs.has(input)) return;
    const inputRect = input.getBoundingClientRect();
    if (!inputRect || inputRect.width < 4 || inputRect.height < 4) return;
    if (headerBottom > 0 && inputRect.top < headerBottom - 8) return;
    const labelNorm = labelFromPropertyList(cell);
    if (!labelNorm || labelNorm === '商品属性' || labelNorm === '填写率') return;
    const cellRect = cell.getBoundingClientRect();
    seenInputs.add(input);
    rows.push({
      input,
      cell,
      labelNorm,
      top: cellRect.top || inputRect.top,
      left: cellRect.left || inputRect.left,
      listId: cell.id || '',
    });
  };

  for (const sel of PROPERTY_CELL_SELECTORS) {
    for (const cell of scope.querySelectorAll(sel)) {
      if (seenCells.has(cell)) continue;
      seenCells.add(cell);
      const input = findInputInCell(cell);
      if (!input) continue;
      addRow(cell, input);
    }
  }

  if (rows.length < 8) {
    for (const input of scope.querySelectorAll('[data-testid="beast-core-select-html-input"], input[type="text"], input[type="search"]')) {
      if (!(input instanceof HTMLInputElement)) continue;
      if (input.type === 'hidden' || input.type === 'file') continue;
      if (seenInputs.has(input)) continue;
      const inputRect = input.getBoundingClientRect();
      if (!inputRect || inputRect.width < 4 || inputRect.height < 4) continue;
      if (headerBottom > 0 && inputRect.top < headerBottom - 8) continue;
      const cell = input.closest('div[id^="property-list-"]')
        || input.closest('[class*="property-list"]')
        || input.closest('[class*="PropertyItemItem"]')
        || input.parentElement;
      addRow(cell, input);
    }
  }

  rows.sort((a, b) => {
    const rowGap = 16;
    if (Math.abs(a.top - b.top) > rowGap) return a.top - b.top;
    return a.left - b.left;
  });
  return rows;
};

const pickFieldCandidate = (rows, needle) => {
  const candidates = rows.filter((r) => r.labelNorm === needle);
  if (!candidates.length) return null;
  if (candidates.length === 1) return candidates[0];
  if (RIGHT_COLUMN_LABELS.has(needle)) {
    candidates.sort((a, b) => b.left - a.left);
  } else {
    candidates.sort((a, b) => a.left - b.left);
  }
  return candidates[0];
};

const propertyPageDebug = (scopeInfo) => {
  const scope = scopeInfo.scope || document.body;
  return {
    cellsById: document.querySelectorAll('div[id^="property-list-"]').length,
    cellsByClass: document.querySelectorAll('[class*="property-list"]').length,
    cellsPropertyItem: document.querySelectorAll('[class*="PropertyItemItem"]').length,
    cellsInScope: countPropertyCells(scope),
    selectInputsInScope: scope.querySelectorAll('[data-testid="beast-core-select-html-input"]').length,
  };
};
"""

_INSPECT_PROPERTY_PAGE_JS = (
    _PROPERTY_FIELD_JS_CORE
    + """
() => {
  let sectionVisible = false;
  let sectionText = '';
  for (const el of document.querySelectorAll('div,span,label,h3,h4')) {
    const t = (el.textContent || '').trim();
    if (t === '商品属性' || (t.startsWith('商品属性') && t.length <= 30)) {
      sectionVisible = true;
      sectionText = t.slice(0, 40);
      break;
    }
  }

  const scopeInfo = findPropertyScope();
  const scopeInputCount = scopeInfo.scope.querySelectorAll(
    '[data-testid="beast-core-select-html-input"]'
  ).length;
  const rows = collectPropertyFields(scopeInfo).map((r) => ({
    label: r.labelNorm,
    labelNorm: r.labelNorm,
    top: r.top,
    left: r.left,
    listId: r.listId,
    textPreview: String(r.cell.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 80),
  }));

  const inputSelectors = [
    '[data-testid="beast-core-select-html-input"]',
    '[class*="IPT_input"]',
  ];
  const seenInputs = new Set();
  const inputs = [];
  for (const sel of inputSelectors) {
    for (const el of document.querySelectorAll(sel)) {
      if (!(el instanceof HTMLInputElement)) continue;
      if (el.type === 'hidden' || el.type === 'file') continue;
      if (seenInputs.has(el)) continue;
      seenInputs.add(el);
      inputs.push({
        placeholder: el.placeholder || '',
        value: el.value || '',
        testid: el.getAttribute('data-testid') || '',
      });
    }
  }

  const titleInput = document.querySelector(
    'input[placeholder*="商品标题"], input[placeholder*="标题组成"], [class*="IPT_input"]'
  );

  return {
    url: location.href,
    sectionVisible,
    sectionText,
    titlePresent: !!titleInput,
    titleValue: titleInput ? String(titleInput.value || '').slice(0, 60) : '',
    inputCount: inputs.length,
    inputs: inputs.slice(0, 20),
    scopeInputCount,
    propertyRowCount: rows.length,
    propertyRows: rows,
    propertyRowLabels: rows.map((r) => r.label),
    domDebug: propertyPageDebug(scopeInfo),
    listboxVisible: !!document.querySelector('ul[role="listbox"]'),
    portalVisible: !!document.querySelector('[data-testid="beast-core-portal-main"]'),
  };
}
"""
)

_MARK_PROPERTY_INPUT_JS = (
    _PROPERTY_FIELD_JS_CORE
    + """
({ fieldKey, labelNeedle }) => {
  const needle = norm(labelNeedle);

  document.querySelectorAll(`[data-pdd-property-target="${fieldKey}"]`).forEach((el) => {
    el.removeAttribute('data-pdd-property-target');
    el.removeAttribute('data-pdd-property-label');
    el.removeAttribute('data-pdd-property-match');
  });

  const scopeInfo = findPropertyScope();
  const rows = collectPropertyFields(scopeInfo);
  const labels = rows.map((r) => r.labelNorm);

  const item = pickFieldCandidate(rows, needle);
  if (item) {
    try { item.input.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
    item.input.setAttribute('data-pdd-property-target', fieldKey);
    item.input.setAttribute('data-pdd-property-label', labelNeedle);
    item.input.setAttribute('data-pdd-property-match', 'row_label');
    return {
      ok: true,
      match: 'row_label',
      labelNorm: item.labelNorm,
      total: rows.length,
      labels,
      listId: item.listId,
      position: { top: item.top, left: item.left },
    };
  }

  return { ok: false, total: rows.length, labels, needle, reason: 'label_not_found' };
}
"""
)

_COUNT_PROPERTY_INPUTS_JS = """
() => {
  const sels = [
    '[data-testid="beast-core-select-html-input"]',
    '[class*="IPT_input"]',
  ];
  const seen = new Set();
  let count = 0;
  for (const sel of sels) {
    for (const el of document.querySelectorAll(sel)) {
      if (!(el instanceof HTMLInputElement)) continue;
      if (el.type === 'hidden' || el.type === 'file') continue;
      if (seen.has(el)) continue;
      seen.add(el);
      count += 1;
    }
  }
  return count;
}
"""


def _norm_text(value: str) -> str:
    return str(value or "").replace(" ", "").replace("\u3000", "").strip()


def _reason_code(reason: str) -> str:
    return REASON_CODES.get(str(reason or "").strip(), f"ATTR_{str(reason or 'unknown').upper()}")


def _reason_hint(code: str) -> str:
    return REASON_HINTS.get(code, "请查看同条日志中的 page_diag / options 字段")


def _log(
    account_id: str,
    listing_label: str,
    message: str,
    *,
    level: str = "INFO",
    field: str = "",
) -> None:
    parts = [f"[{LOG_TAG}]", f"[{level}]"]
    if account_id:
        parts.append(f"[{account_id}]")
    if listing_label:
        parts.append(f"[{listing_label}]")
    if field:
        parts.append(f"[{field}]")
    parts.append(message)
    print(" ".join(parts), flush=True)


def _log_json(
    account_id: str,
    listing_label: str,
    event: str,
    payload: dict[str, Any],
    *,
    level: str = "INFO",
    field: str = "",
) -> None:
    try:
        body = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        body = str(payload)
    _log(account_id, listing_label, f"{event} {body}", level=level, field=field)


def _inspect_property_page(raw) -> dict[str, Any]:
    try:
        data = raw.evaluate(_INSPECT_PROPERTY_PAGE_JS)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        return {"inspect_error": _safe_exc(exc)}


def _is_skip_option_text(text: str) -> bool:
    t = str(text or "").strip()
    if not t or t in NO_RESULT_PHRASES:
        return True
    return any(skip in t for skip in SKIP_OPTION_PHRASES)


def _row_matches_label(row_text: str, label: str) -> bool:
    norm_label = _norm_text(label)
    if not norm_label:
        return False
    lines = [_norm_text(line) for line in str(row_text or "").splitlines() if _norm_text(line)]
    if norm_label in lines:
        return True
    norm_row = _norm_text(row_text)
    if norm_row == norm_label:
        return True
    if norm_label.endswith("材质") and "材质" in norm_row and "重要" in norm_row:
        return True
    if len(norm_label) >= 3 and norm_label in norm_row and len(norm_row) <= len(norm_label) + 28:
        return True
    return False


def load_enabled_listing_product_attributes() -> list[dict[str, str]]:
    """读取 enabled 商品属性配置；MySQL 不可用时回退默认种子。"""
    try:
        from pdd_agent.db.repositories import list_listing_product_attributes, seed_listing_product_attributes
        from pdd_agent.db.session import is_database_available

        if is_database_available():
            seed_listing_product_attributes()
            rows = list_listing_product_attributes(enabled_only=True)
            items = [
                {
                    "field_key": row.field_key,
                    "label": row.label,
                    "selected_value": str(row.selected_value or "").strip(),
                }
                for row in rows
                if row.enabled and str(row.selected_value or "").strip()
            ]
            if items:
                return items
    except Exception:
        pass

    from pdd_agent.domain.listing_product_attributes import DEFAULT_LISTING_PRODUCT_ATTRIBUTES

    return [
        {
            "field_key": item.field_key,
            "label": item.label,
            "selected_value": item.selected_value,
        }
        for item in DEFAULT_LISTING_PRODUCT_ATTRIBUTES
        if item.enabled and item.selected_value
    ]


def _count_property_inputs(raw) -> int:
    try:
        return int(raw.evaluate(_COUNT_PROPERTY_INPUTS_JS) or 0)
    except Exception:
        return 0


def _scroll_product_attributes_section(raw) -> None:
    try:
        raw.evaluate(_SCROLL_PRODUCT_ATTRIBUTES_JS)
    except Exception:
        pass
    time.sleep(0.2)


def _close_open_dropdown(raw) -> None:
    try:
        raw.keyboard.press("Escape")
        time.sleep(0.12)
    except Exception:
        pass


def _wait_for_product_attributes_ready(
    raw,
    *,
    account_id: str = "",
    listing_label: str = "",
    min_property_rows: int = 8,
    timeout_s: float = 25.0,
) -> tuple[bool, dict[str, Any]]:
    _scroll_product_attributes_section(raw)
    deadline = time.time() + timeout_s
    last_diag: dict[str, Any] = {}
    while time.time() < deadline:
        last_diag = _inspect_property_page(raw)
        property_row_count = int(last_diag.get("propertyRowCount") or 0)
        section_visible = bool(last_diag.get("sectionVisible"))
        if section_visible and property_row_count >= min_property_rows:
            _log_json(
                account_id,
                listing_label,
                "page_ready",
                {
                    "property_row_count": property_row_count,
                    "input_count": last_diag.get("inputCount"),
                    "scope_input_count": last_diag.get("scopeInputCount"),
                    "dom_debug": last_diag.get("domDebug"),
                    "waited_s": round(timeout_s - (deadline - time.time()), 1),
                },
            )
            return True, last_diag
        time.sleep(0.5)
        _scroll_product_attributes_section(raw)

    property_row_count = int(last_diag.get("propertyRowCount") or 0)
    _log_json(
        account_id,
        listing_label,
        "page_wait_timeout",
        {
            "property_row_count": property_row_count,
            "min_property_rows": min_property_rows,
            "section_visible": last_diag.get("sectionVisible"),
            "property_rows": [r.get("label") for r in (last_diag.get("propertyRows") or [])[:12]],
            "dom_debug": last_diag.get("domDebug"),
            "url": last_diag.get("url"),
        },
        level="WARN",
    )
    return property_row_count > 0, last_diag


def _mark_property_input(
    raw,
    *,
    field_key: str,
    label: str,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "label": label,
        "field_key": field_key,
    }
    try:
        result = raw.evaluate(
            _MARK_PROPERTY_INPUT_JS,
            {"fieldKey": field_key, "labelNeedle": label},
        )
        if isinstance(result, dict):
            meta.update(result)
        return meta
    except Exception as exc:
        meta["ok"] = False
        meta["resolve_error"] = _safe_exc(exc)
        return meta


def _property_input_locator(raw, field_key: str):
    key = str(field_key or "").strip()
    if not key:
        return None
    loc = raw.locator(f'[data-pdd-property-target="{key}"]')
    try:
        if loc.count() <= 0:
            return None
    except Exception:
        return None
    return loc.first


def _focus_and_type_property_value(
    raw,
    *,
    field_key: str,
    label: str,
    value: str,
) -> dict[str, Any]:
    meta = _mark_property_input(
        raw,
        field_key=field_key,
        label=label,
    )
    if not meta.get("ok"):
        page_diag = _inspect_property_page(raw)
        return {
            "ok": False,
            "reason": "not_found",
            "meta": meta,
            "input_count": page_diag.get("inputCount"),
            "property_row_labels": meta.get("labels") or [],
        }

    inp = _property_input_locator(raw, field_key)
    if inp is None:
        return {
            "ok": False,
            "reason": "not_found",
            "meta": meta,
            "input_count": _count_property_inputs(raw),
        }

    try:
        inp.scroll_into_view_if_needed(timeout=3000)
        inp.click(timeout=3000, force=True)
        time.sleep(0.15)
        inp.fill("")
        time.sleep(0.08)
        inp.fill(value)
        inp.dispatch_event("input")
        inp.dispatch_event("change")
        time.sleep(0.15)
        typed = inp.input_value(timeout=1000)
        return {"ok": True, "value": value, "method": "locator_fill", "typed": typed, "meta": meta}
    except Exception:
        try:
            inp.click(force=True)
            raw.keyboard.press("Control+A")
            raw.keyboard.type(value, delay=45)
            return {"ok": True, "value": value, "method": "keyboard", "meta": meta}
        except Exception as exc2:
            return {
                "ok": False,
                "reason": "type_failed",
                "error": _safe_exc(exc2),
                "meta": meta,
                "input_count": _count_property_inputs(raw),
            }


def _collect_visible_dropdown_options(raw) -> tuple[list[tuple[Any, str]], dict[str, Any]]:
    collected: list[tuple[Any, str]] = []
    seen: set[str] = set()
    debug: dict[str, Any] = {"selectors": {}}

    for selector in DROPDOWN_OPTION_SELECTORS:
        opts = raw.locator(selector)
        try:
            count = opts.count()
        except Exception:
            count = 0
        debug["selectors"][selector] = count
        if count <= 0:
            continue

        visible_count = 0
        for idx in range(min(count, 60)):
            opt = opts.nth(idx)
            try:
                if not opt.is_visible():
                    continue
            except Exception:
                continue
            visible_count += 1
            try:
                text = (opt.inner_text(timeout=300) or "").strip()
            except Exception:
                continue
            if _is_skip_option_text(text):
                continue
            key = _norm_text(text)
            if not key or key in seen:
                continue
            seen.add(key)
            collected.append((opt, text))

        if collected:
            debug["matched_selector"] = selector
            debug["visible_count"] = visible_count
            break

    try:
        listboxes = raw.locator('ul[role="listbox"]')
        debug["listbox_count"] = listboxes.count()
        if listboxes.count() > 0:
            debug["listbox_text"] = (listboxes.last.inner_text(timeout=400) or "").strip()[:200]
    except Exception:
        pass

    return collected, debug


def _page_shows_only_no_result(raw) -> bool:
    options, _ = _collect_visible_dropdown_options(raw)
    if options:
        return False
    try:
        listboxes = raw.locator('ul[role="listbox"]')
        for idx in range(min(listboxes.count(), 3)):
            box = listboxes.nth(idx)
            try:
                if not box.is_visible():
                    continue
            except Exception:
                continue
            body = (box.inner_text(timeout=300) or "").strip()
            if body and any(p in body for p in NO_RESULT_PHRASES):
                return True
    except Exception:
        pass
    return False


def _option_matches(text: str, target: str) -> bool:
    normalized = _norm_text(text)
    tgt = _norm_text(target)
    if not tgt:
        return False
    if normalized == tgt:
        return True
    if len(tgt) >= 4 and tgt in normalized:
        return True
    return False


def _dropdown_options_match_field(options: list[str], label: str) -> bool:
    """下拉选项是否与目标字段语义一致（防止点错相邻列输入框）。"""
    if not options:
        return True
    joined = " ".join(str(o) for o in options)
    brand_markers = ("无品牌/无注册商标", "Pepsi/百事", "Montblanc/万宝龙", "更多品牌请搜索")
    if label != "品牌" and any(marker in joined for marker in brand_markers):
        return False
    if label == "品牌":
        return any(marker in joined for marker in brand_markers) or "品牌" in joined
    return True


def _click_dropdown_option(opt) -> None:
    opt.scroll_into_view_if_needed(timeout=2000)
    opt.evaluate(
        """(el) => {
          el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true }));
          el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
          el.click();
          el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
          el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true }));
        }"""
    )


def _wait_and_pick_dropdown_option(
    raw,
    value: str,
    *,
    account_id: str = "",
    listing_label: str = "",
    field: str = "",
    max_wait_s: float = 18.0,
) -> dict[str, Any]:
    deadline = time.time() + max_wait_s
    last_options: list[str] = []
    last_debug: dict[str, Any] = {}
    no_result_seen = False

    while time.time() < deadline:
        if _page_shows_only_no_result(raw):
            no_result_seen = True
            time.sleep(0.5)
            continue

        options, last_debug = _collect_visible_dropdown_options(raw)
        if not options:
            time.sleep(0.45)
            continue

        last_options = [text for _, text in options[:15]]

        for opt, text in options:
            if _option_matches(text, value):
                try:
                    _click_dropdown_option(opt)
                    time.sleep(0.35)
                    return {
                        "ok": True,
                        "picked": text,
                        "no_result_seen": no_result_seen,
                        "dropdown_debug": last_debug,
                    }
                except Exception as exc:
                    return {
                        "ok": False,
                        "reason": "click_failed_option",
                        "error": _safe_exc(exc),
                        "options": last_options,
                        "dropdown_debug": last_debug,
                    }

        _log_json(
            account_id,
            listing_label,
            "option_mismatch",
            {
                "want": value,
                "got": last_options,
                "dropdown_debug": last_debug,
                "no_result_seen": no_result_seen,
            },
            level="WARN",
            field=field,
        )
        return {
            "ok": False,
            "reason": "option_not_found",
            "options": last_options,
            "dropdown_debug": last_debug,
            "no_result_seen": no_result_seen,
        }

    _log_json(
        account_id,
        listing_label,
        "dropdown_timeout",
        {
            "want": value,
            "last_options": last_options,
            "dropdown_debug": last_debug,
            "no_result_seen": no_result_seen,
            "waited_s": max_wait_s,
        },
        level="WARN",
        field=field,
    )
    return {
        "ok": False,
        "reason": "timeout",
        "options": last_options,
        "dropdown_debug": last_debug,
        "no_result_seen": no_result_seen,
    }


def _build_failure_result(
    *,
    label: str,
    value: str,
    reason: str,
    field_key: str = "",
    page_diag: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    code = _reason_code(reason)
    result: dict[str, Any] = {
        "ok": False,
        "label": label,
        "field_key": field_key,
        "value": value,
        "reason": reason,
        "code": code,
        "hint": _reason_hint(code),
    }
    if page_diag:
        result["page_diag"] = page_diag
    if extra:
        result.update(extra)
    return result


def _log_field_failure(
    account_id: str,
    listing_label: str,
    result: dict[str, Any],
) -> None:
    _log_json(
        account_id,
        listing_label,
        "field_failed",
        {
            "code": result.get("code"),
            "reason": result.get("reason"),
            "hint": result.get("hint"),
            "label": result.get("label"),
            "field_key": result.get("field_key"),
            "value": result.get("value"),
            "options": result.get("options") or [],
            "input_count": result.get("input_count"),
            "match": (result.get("meta") or {}).get("match"),
            "label_norm": (result.get("meta") or {}).get("labelNorm"),
            "property_row_labels": (result.get("meta") or {}).get("labels")
            or result.get("property_row_labels")
            or [],
            "dropdown_debug": result.get("dropdown_debug"),
            "page_diag": {
                "section_visible": (result.get("page_diag") or {}).get("sectionVisible"),
                "input_count": (result.get("page_diag") or {}).get("inputCount"),
                "property_rows": [
                    r.get("label") for r in ((result.get("page_diag") or {}).get("propertyRows") or [])[:12]
                ],
            },
        },
        level="ERROR",
        field=str(result.get("label") or ""),
    )


def fill_listing_product_attribute_field(
    page: DpPage,
    *,
    account_id: str,
    label: str,
    value: str,
    listing_label: str = "",
    field_key: str = "",
    page_diag: dict[str, Any] | None = None,
    max_wait_s: float = 18.0,
) -> dict[str, Any]:
    """填写单个商品属性搜索下拉框。"""
    raw = page._page
    value = str(value or "").strip()
    label = str(label or "").strip()
    if not label or not value:
        return _build_failure_result(label=label, value=value, reason="empty_label_or_value", field_key=field_key)

    _log(
        account_id,
        listing_label,
        f"开始 field_key={field_key or '-'} value={value!r}",
        field=label,
    )
    _close_open_dropdown(raw)
    _scroll_product_attributes_section(raw)

    fk = field_key or label
    locate_meta = _mark_property_input(
        raw,
        field_key=fk,
        label=label,
    )
    inp = _property_input_locator(raw, fk) if locate_meta.get("ok") else None

    if inp is None:
        diag = page_diag or _inspect_property_page(raw)
        input_count = int(diag.get("inputCount") or 0)
        if input_count <= 0:
            _log(account_id, listing_label, "输入框为 0，额外等待 5s 后重试定位…", field=label)
            time.sleep(5)
            _scroll_product_attributes_section(raw)
            locate_meta = _mark_property_input(
                raw,
                field_key=fk,
                label=label,
            )
            inp = _property_input_locator(raw, fk)
            diag = _inspect_property_page(raw)

        if inp is None:
            reason = "section_not_ready" if int(diag.get("inputCount") or 0) < 3 else "not_found"
            result = _build_failure_result(
                label=label,
                value=value,
                reason=reason,
                field_key=field_key,
                page_diag=diag,
                extra={
                    "meta": locate_meta,
                    "input_count": diag.get("inputCount"),
                    "property_row_labels": locate_meta.get("labels") or [],
                },
            )
            _log_field_failure(account_id, listing_label, result)
            return result

    _log_json(
        account_id,
        listing_label,
        "located",
        locate_meta,
        field=label,
    )

    try:
        inp.scroll_into_view_if_needed(timeout=3000)
        inp.click(timeout=3000, force=True)
    except Exception as exc:
        result = _build_failure_result(
            label=label,
            value=value,
            reason="click_failed",
            field_key=field_key,
            extra={"error": _safe_exc(exc), "meta": locate_meta},
        )
        _log_field_failure(account_id, listing_label, result)
        return result

    time.sleep(0.45)
    pick_result = _wait_and_pick_dropdown_option(
        raw,
        value,
        account_id=account_id,
        listing_label=listing_label,
        field=label,
        max_wait_s=4.0,
    )
    if pick_result.get("ok"):
        _log(account_id, listing_label, f"完成（点击即选）→ {pick_result.get('picked')}", field=label)
        _close_open_dropdown(raw)
        return {"ok": True, "label": label, "field_key": field_key, "value": value, **pick_result}

    options = pick_result.get("options") or []
    if options and not _dropdown_options_match_field(options, label):
        _close_open_dropdown(raw)
        result = _build_failure_result(
            label=label,
            value=value,
            reason="not_found",
            field_key=field_key,
            extra={
                "meta": locate_meta,
                "options": options,
                "dropdown_debug": pick_result.get("dropdown_debug"),
                "wrong_field_dropdown": True,
            },
        )
        result["hint"] = "下拉选项与字段不匹配（可能定位到了相邻列），请查看 located.position.left"
        _log_field_failure(account_id, listing_label, result)
        return result

    type_result = _focus_and_type_property_value(
        raw,
        field_key=fk,
        label=label,
        value=value,
    )
    if not type_result.get("ok"):
        result = _build_failure_result(
            label=label,
            value=value,
            reason=str(type_result.get("reason") or "type_failed"),
            field_key=field_key,
            extra={
                "error": type_result.get("error", ""),
                "meta": type_result.get("meta"),
                "input_count": type_result.get("input_count"),
            },
        )
        _log_field_failure(account_id, listing_label, result)
        return result

    _log(
        account_id,
        listing_label,
        f"已输入 typed={type_result.get('typed')!r} method={type_result.get('method')}，等待下拉…",
        field=label,
    )
    time.sleep(0.45)
    pick_result = _wait_and_pick_dropdown_option(
        raw,
        value,
        account_id=account_id,
        listing_label=listing_label,
        field=label,
        max_wait_s=max_wait_s,
    )
    if pick_result.get("ok"):
        _log(account_id, listing_label, f"完成 → {pick_result.get('picked')}", field=label)
        _close_open_dropdown(raw)
        return {"ok": True, "label": label, "field_key": field_key, "value": value, **pick_result}

    _close_open_dropdown(raw)

    result = _build_failure_result(
        label=label,
        value=value,
        reason=str(pick_result.get("reason") or "pick_failed"),
        field_key=field_key,
        extra={
            "options": pick_result.get("options") or [],
            "dropdown_debug": pick_result.get("dropdown_debug"),
            "no_result_seen": pick_result.get("no_result_seen"),
            "meta": locate_meta,
        },
    )
    _log_field_failure(account_id, listing_label, result)
    return result


def fill_listing_product_attributes(
    page: DpPage,
    account_id: str,
    *,
    listing_label: str = "",
    attributes: list[dict[str, str]] | None = None,
    max_wait_s: float = 18.0,
) -> dict[str, Any]:
    """
    填完标题后调用：按数据库/默认配置填写商品属性区所有 enabled 字段。
    跳过 是否透明 / 是否有夹层 / 产品类型（DB 中 enabled=false）。
    """
    items = attributes if attributes is not None else load_enabled_listing_product_attributes()
    if not items:
        return {"ok": False, "reason": "no_attributes_configured", "filled": [], "failed": []}

    raw = page._page
    _log(account_id, listing_label, f"开始填写商品属性（共 {len(items)} 项）")
    ready, page_diag = _wait_for_product_attributes_ready(
        raw,
        account_id=account_id,
        listing_label=listing_label,
        min_property_rows=min(8, len(items)),
    )
    _log_json(
        account_id,
        listing_label,
        "page_snapshot",
        {
            "ready": ready,
            "section_visible": page_diag.get("sectionVisible"),
            "input_count": page_diag.get("inputCount"),
            "property_row_count": page_diag.get("propertyRowCount"),
            "scope_input_count": page_diag.get("scopeInputCount"),
            "dom_debug": page_diag.get("domDebug"),
            "property_rows": page_diag.get("propertyRowLabels")
            or [r.get("label") for r in (page_diag.get("propertyRows") or [])],
            "title_value": page_diag.get("titleValue"),
            "url": page_diag.get("url"),
        },
    )
    if not ready:
        _log(
            account_id,
            listing_label,
            "商品属性区未完全就绪，仍继续尝试（详见 page_snapshot）",
            level="WARN",
        )
    time.sleep(0.35)

    filled: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for item in items:
        label = str(item.get("label") or "").strip()
        value = str(item.get("selected_value") or "").strip()
        field_key = str(item.get("field_key") or "").strip()
        if not label or not value:
            continue

        result = fill_listing_product_attribute_field(
            page,
            account_id=account_id,
            label=label,
            value=value,
            listing_label=listing_label,
            field_key=field_key,
            page_diag=page_diag,
            max_wait_s=max_wait_s,
        )
        if result.get("ok"):
            filled.append(result)
        else:
            failed.append(result)
        time.sleep(0.25)

    ok = len(failed) == 0
    fail_codes = [str(item.get("code") or "") for item in failed]
    _log_json(
        account_id,
        listing_label,
        "summary",
        {
            "ok": ok,
            "filled_count": len(filled),
            "failed_count": len(failed),
            "failed_codes": fail_codes,
            "failed_labels": [item.get("label") for item in failed],
        },
        level="INFO" if ok else "WARN",
    )
    return {
        "ok": ok,
        "filled_count": len(filled),
        "failed_count": len(failed),
        "filled": filled,
        "failed": failed,
        "page_diag": page_diag,
    }
