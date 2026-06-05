"""多规格（款式 + 型号）拼多多页面填写。"""
import time

from pdd_auto.listing.helpers import _xpath_literal, fill_sku_row_inputs


def _spec_row_boxes(page):
    container = page.ele("#spec", timeout=3)
    if not container:
        return container, []
    boxes = container.eles("css:.goods-spec-row-box")
    return container, boxes


def _inputs_in_box(box):
    return box.eles("tag:input@placeholder=请输入规格名称") if box else []


def _wait_inputs_count(box, count: int, account_id: str, label: str, max_wait: int = 25) -> bool:
    for attempt in range(max_wait):
        cur = len(_inputs_in_box(box))
        if cur >= count:
            return True
        print(f"[{account_id}] 等待{label}规格框 ({cur}/{count}) ({attempt + 1}/{max_wait})")
        time.sleep(0.5)
    return False


def _add_values_to_spec_box(page, box, account_id: str, label: str, names: list[str]):
    """向单个规格维度（款式或型号）逐个录入名称。"""
    if not names:
        return

    for i, name in enumerate(names):
        if i > 0:
            _wait_inputs_count(box, i + 1, account_id, label)

        inputs = _inputs_in_box(box)
        if not inputs:
            print(f"[{account_id}] 未找到{label}规格输入框")
            return

        current = inputs[-1]
        current.scroll.to_see()
        current.click()
        time.sleep(0.2)
        current.input(name, clear=True)
        time.sleep(0.4)
        current.input("\n")
        time.sleep(0.5)
        page.run_js("arguments[0].blur();", current)
        print(f"[{account_id}] 已录入{label} ({i + 1}/{len(names)})：{name}")


def _ensure_second_spec_box(page, account_id: str):
    """尝试添加第二个规格维度（型号）。"""
    _, boxes = _spec_row_boxes(page)
    if len(boxes) >= 2:
        return boxes

    add_btn = page.ele("text:添加规格类型", timeout=2) or page.ele("text:添加规格", timeout=2)
    if add_btn:
        add_btn.click()
        time.sleep(1.5)
        _, boxes = _spec_row_boxes(page)
        print(f"[{account_id}] 已点击添加规格，当前 {len(boxes)} 个规格组")
    return boxes


def _select_spec_type(box, type_name: str, page, account_id: str):
    """在规格组下拉框中选择「款式」或「型号」。"""
    if not box:
        return
    trigger = box.ele("css:.ant-select-selector", timeout=1) or box.ele("tag:select", timeout=1)
    if trigger:
        trigger.click()
        time.sleep(0.5)
        option = page.ele(f"text:{type_name}", timeout=2)
        if option:
            option.click()
            time.sleep(0.5)
            print(f"[{account_id}] 已选择规格类型：{type_name}")


def add_style_and_model_specs(
    page,
    account_id: str,
    style_names: list[str],
    model_names: list[str],
):
    """
    图三：录入两个规格维度。
    第 1 组 → 款式；第 2 组 → 型号。
    """
    _, boxes = _spec_row_boxes(page)
    if not boxes:
        print(f"[{account_id}] 未找到 #spec 规格区域")
        return False

    _select_spec_type(boxes[0], "款式", page, account_id)
    _add_values_to_spec_box(page, boxes[0], account_id, "款式", style_names)

    boxes = _ensure_second_spec_box(page, account_id)
    if len(boxes) < 2:
        print(f"[{account_id}] 未能创建第二个规格组（型号），仍将尝试继续")
        if boxes:
            _add_values_to_spec_box(page, boxes[0], account_id, "型号", model_names)
        return False

    _select_spec_type(boxes[1], "型号", page, account_id)
    _add_values_to_spec_box(page, boxes[1], account_id, "型号", model_names)
    return True


def wait_multi_sku_rows(page, account_id: str, skus: list, max_wait: int = 30) -> bool:
    """等待价格表生成足够的 SKU 行。"""
    for attempt in range(max_wait):
        ready = 0
        for sku in skus:
            style = sku.style_name if hasattr(sku, "style_name") else sku.get("style_name", "")
            model = sku.model_name if hasattr(sku, "model_name") else sku.get("model_name", "")
            if not style or not model:
                continue
            ls, lm = _xpath_literal(style), _xpath_literal(model)
            row = page.ele(f"xpath://tr[contains(., {ls}) and contains(., {lm})]", timeout=0.5)
            if row:
                ready += 1
        if ready >= len(skus):
            print(f"[{account_id}] 多规格价格表就绪：{ready}/{len(skus)} 行")
            return True
        print(
            f"[{account_id}] 等待多规格价格表 ({ready}/{len(skus)}) "
            f"({attempt + 1}/{max_wait})..."
        )
        page.scroll.down(300)
        time.sleep(1)
    print(f"[{account_id}] 多规格价格表未完全生成，仍将尝试填写")
    return False


def get_sku_row_by_style_model(page, style_name: str, model_name: str, max_wait: int = 12):
    ls, lm = _xpath_literal(style_name), _xpath_literal(model_name)
    xpath = f"xpath://tr[contains(., {ls}) and contains(., {lm})]"
    for _ in range(max_wait):
        row = page.ele(xpath, timeout=2)
        if row:
            return row
        page.scroll.down(300)
        time.sleep(0.8)
    return None


def upload_row_preview(row, image_path: str, account_id: str, label: str) -> bool:
    try:
        upload_input = row.ele("xpath:.//input[@type=\"file\"]", timeout=3)
        if not upload_input:
            print(f"[{account_id}] 未找到 [{label}] 预览图上传框")
            return False
        upload_input.input(image_path)
        print(f"[{account_id}] 已上传预览图 [{label}]：{image_path}")
        time.sleep(3.0)
        return True
    except Exception as e:
        print(f"[{account_id}] 预览图上传失败 [{label}]：{e}")
        return False


def fill_multi_spec_rows(page, account_id: str, skus: list, defaults: dict):
    """图四：逐行填写库存/价格/编码并上传预览图（按中文款式名+型号名定位行）。"""
    for i, sku in enumerate(skus):
        label = f"{sku.style_name} / {sku.model_name}"
        print(f"[{account_id}] >>> SKU {i + 1}/{len(skus)}：{label}")

        row = get_sku_row_by_style_model(page, sku.style_name, sku.model_name)
        if not row:
            print(f"[{account_id}] 未找到价格表行：{label}")
            continue

        row.scroll.to_see()
        time.sleep(0.8)

        row_data = {
            "inventory": defaults.get("inventory", "10"),
            "group_price": defaults.get("group_price", "199.9"),
            "single_price": defaults.get("single_price", "299.9"),
            # 规格编码 = 预览图上一级目录名，如 BD199A+BD188A
            "sku_code": sku.combo_folder,
        }
        ok, count = fill_sku_row_inputs(row, row_data)
        if not ok:
            print(f"[{account_id}] 行内输入框不足（{count} 个），跳过：{label}")
            continue

        if sku.preview_image:
            upload_row_preview(row, str(sku.preview_image.resolve()), account_id, label)

        print(
            f"[{account_id}] 完成 SKU：{label}，规格编码={sku.combo_folder}"
        )
