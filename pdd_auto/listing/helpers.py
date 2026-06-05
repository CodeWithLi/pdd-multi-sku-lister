"""上架流程：SKU 表格、图片路径等辅助函数。"""
import glob
import os
import time


def get_images_from_folder(folder_path, prefix):
    abs_folder_path = os.path.abspath(folder_path)
    patterns = (
        os.path.join(abs_folder_path, f"{prefix}_*.png"),
        os.path.join(abs_folder_path, f"{prefix}_*.jpg"),
        os.path.join(abs_folder_path, f"{prefix}_*.jpeg"),
    )
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    return files


def _xpath_literal(text):
    if text is None:
        return "''"
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    parts = text.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"


def wait_sku_price_rows(page, account_id, skus_list, max_wait=25):
    for attempt in range(max_wait):
        ready = 0
        for sku in skus_list:
            spec_name = sku.get("spec_name", "")
            if not spec_name:
                continue
            lit = _xpath_literal(spec_name)
            row = page.ele(f"xpath://tr[contains(., {lit})]", timeout=1)
            if row:
                ready += 1
        if ready >= len(skus_list):
            print(f"[{account_id}] 价格表格已就绪：{ready}/{len(skus_list)} 行")
            return True
        print(f"[{account_id}] 等待价格表格 ({ready}/{len(skus_list)}) ({attempt + 1}/{max_wait})...")
        page.scroll.down(300)
        time.sleep(1)
    print(f"[{account_id}] 价格表格未完全生成，仍将尝试按行填写")
    return False


def get_sku_row_by_spec(page, spec_name, max_wait=12):
    lit = _xpath_literal(spec_name)
    for _ in range(max_wait):
        row = page.ele(f"xpath://tr[contains(., {lit})]", timeout=2)
        if row:
            return row
        page.scroll.down(300)
        time.sleep(0.8)
    return None


def fill_sku_row_inputs(row, sku):
    inputs = row.eles("xpath:.//input[@placeholder=\"请输入\"]")
    if len(inputs) < 4:
        return False, len(inputs)

    fields = [
        ("inventory", 0),
        ("group_price", 1),
        ("single_price", 2),
        ("sku_code", 3),
    ]
    for key, idx in fields:
        val = sku.get(key)
        if val is None:
            continue
        inputs[idx].click()
        time.sleep(0.1)
        inputs[idx].input(str(val), clear=True)
    return True, len(inputs)


def count_spec_name_inputs(target):
    return len(target.eles("tag:input@placeholder=请输入规格名称"))


def wait_next_spec_input(target, account_id, prev_count, max_wait=20):
    for attempt in range(max_wait):
        cur = count_spec_name_inputs(target)
        if cur > prev_count:
            print(f"[{account_id}] 下一个规格输入框已出现 ({prev_count} → {cur})")
            return cur
        time.sleep(0.5)
    print(f"[{account_id}] 等待下一个规格输入框超时（仍为 {prev_count} 个）")
    return prev_count


def add_spec_names_one_by_one(page, target, account_id, skus_list):
    for i, sku in enumerate(skus_list):
        spec_name = sku.get("spec_name", "")
        if not spec_name:
            continue

        if i > 0:
            need = i + 1
            for attempt in range(20):
                cur = count_spec_name_inputs(target)
                if cur >= need:
                    break
                print(
                    f"[{account_id}] 等待第 {i + 1} 个规格空框 ({cur}/{need}) "
                    f"({attempt + 1}/20)..."
                )
                time.sleep(0.5)
            else:
                print(f"[{account_id}] 第 {i + 1} 个规格空框未出现，仍尝试录入：{spec_name}")

        before_count = count_spec_name_inputs(target)
        spec_inputs = target.eles("tag:input@placeholder=请输入规格名称")
        if not spec_inputs:
            print(f"[{account_id}] 未找到规格输入框，无法添加：{spec_name}")
            continue

        current_input = spec_inputs[-1]
        current_input.scroll.to_see()
        current_input.click()
        time.sleep(0.2)
        current_input.input(spec_name, clear=True)
        time.sleep(0.4)
        current_input.input("\n")
        time.sleep(0.5)
        page.run_js("arguments[0].blur();", current_input)
        print(f"[{account_id}] 已录入规格 ({i + 1}/{len(skus_list)})：{spec_name}")

        if i < len(skus_list) - 1:
            wait_next_spec_input(target, account_id, before_count)
