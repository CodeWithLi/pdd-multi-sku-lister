"""商品上架主流程。"""
import os
import random
import time

from pdd_auto.ai.title import resolve_listing_title
from pdd_auto.browser.session import ensure_login
from pdd_auto.config import load_config
from pdd_auto.listing.helpers import (
    add_spec_names_one_by_one,
    fill_sku_row_inputs,
    get_sku_row_by_spec,
    wait_sku_price_rows,
)
from pdd_auto.listing.page_ai_title import apply_title_after_cover_upload
from pdd_auto.paths import chrome_profile_path, error_screenshot_path
from pdd_auto.products.assets import (
    get_carousel_images,
    get_detail_images,
    resolve_account_product_abs_path,
    resolve_account_product_path,
    validate_product_images,
)


def process_single_account(account_config, product_info, config=None):
    account_id = account_config.get("account_id")
    if config is None:
        config = load_config()

    try:
        product_path = resolve_account_product_path(account_config, config)
        product_abs = resolve_account_product_abs_path(account_config, config)
    except ValueError as e:
        print(f"[{account_id}] {e}")
        return

    ok, errors = validate_product_images(product_abs, config)
    if not ok:
        print(f"[{account_id}] 素材目录：{product_path}")
        for err in errors:
            print(f"[{account_id}] {err}")
        print(f"[{account_id}] 轮播/详情图不完整（需 1.jpg～8.jpg），跳过此账号。")
        return

    covers = get_carousel_images(product_abs, config)
    details = get_detail_images(product_abs, config)
    print(
        f"[{account_id}] 素材目录：{product_path} "
        f"（轮播 {len(covers)} 张，详情 {len(details)} 张）"
    )

    username = account_config.get("username", "")
    password = account_config.get("password", "")

    page = ensure_login(account_id, chrome_profile_path(account_id), username, password)
    if not page:
        return

    asset_dir = str(product_abs)

    print(f"\n--- [{account_id}] 开始执行商品上架任务 ---")
    try:
        listing_info = dict(product_info)
        listing_info["title"] = resolve_listing_title(
            product_info, account_id, product_path=asset_dir, config=config
        )
        time.sleep(random.uniform(1.0, 2.0))

        print(f"[{account_id}] 正在跳转商品分类界面...")
        page.get("https://mms.pinduoduo.com/goods/category")
        time.sleep(5)

        ui_type = "A"
        if page.ele("css:.goodsCarousel_btns__22KMn", timeout=1) or page.ele(
            'css:input[data-tracking-click-viewid="local_upload"]', timeout=1
        ):
            ui_type = "C"
        elif page.ele('css:[data-tracking-click-viewid="cate_tree_tab"]', timeout=1):
            ui_type = "B"

        print(f"[{account_id}] 路由判定完成：【分支 {ui_type}】")

        if ui_type == "C":
            section_ele = page.ele("css:.goodsCarousel_btns__22KMn")
            if section_ele:
                page.run_js('arguments[0].style.display = "flex";', section_ele)
            time.sleep(1)

            cover_file_input = page.ele('css:input[data-tracking-click-viewid="local_upload"]')
            if cover_file_input:
                cover_file_input.input(covers)
            time.sleep(random.uniform(1.5, 2.5))

            listing_info["title"] = apply_title_after_cover_upload(
                page, account_id, product_info, listing_info.get("title", "")
            )

            time.sleep(2)
            next_btn = page.ele("#bottomSubmitBtnId")
            if next_btn:
                next_btn.click()
            time.sleep(5)
            page.wait.load_start()

        else:
            if ui_type == "B":
                search_publish_tab = page.ele('css:[data-tracking-click-viewid="cate_tree_tab"]')
                if search_publish_tab:
                    page.run_js("arguments[0].click();", search_publish_tab)
                    time.sleep(3)

            search_input = page.ele('css:input[placeholder="请输入关键词搜索分类"]')
            search_input.click()
            time.sleep(0.5)
            search_input.input(listing_info.get("category_keyword"), clear=True)
            time.sleep(2)

            first_category_item = page.ele("css:li.SPP_searchItem_5-188-0")
            if first_category_item:
                first_category_item.click()
            time.sleep(1)

            if ui_type == "B":
                confirm_btn = page.ele("text:下一步, 完善商品信息")
            else:
                confirm_btn = page.ele("text:确认发布该类商品")
            if confirm_btn:
                confirm_btn.click()

            time.sleep(5)
            page.wait.load_start()

            section_ele = page.ele("css:.uploadImgEnter.uploadImgEnterNew")
            if section_ele:
                page.run_js('arguments[0].style.display = "flex";', section_ele)
            time.sleep(1)
            cover_file_input = page.ele(
                'css:input[type="file"]:not([data-tracking-click-viewid="detail_img_localfile_upload"])'
            )
            if cover_file_input:
                cover_file_input.input(covers)
            time.sleep(random.uniform(1.5, 2.5))

            listing_info["title"] = apply_title_after_cover_upload(
                page, account_id, product_info, listing_info.get("title", "")
            )
            time.sleep(1)

        print(f"[{account_id}] 正在上传详情图...")
        detail_file_input = page.ele(
            'css:input[data-tracking-click-viewid="detail_img_localfile_upload"]'
        )
        if detail_file_input and details:
            detail_file_input.input(details)
        time.sleep(2)

        skus_list = account_config.get("skus", [])
        if not skus_list:
            print(f"[{account_id}] 配置文件中未提供 skus 列表，跳过表格填写")
            return

        print(f"[{account_id}] 正在向 #spec 生成 {len(skus_list)} 个规格名称...")
        spec_container = page.ele("#spec", timeout=3)
        if spec_container:
            first_spec_row_box = spec_container.ele("css:.goods-spec-row-box")
            target = first_spec_row_box if first_spec_row_box else spec_container
            add_spec_names_one_by_one(page, target, account_id, skus_list)
        time.sleep(2)
        wait_sku_price_rows(page, account_id, skus_list)

        print(f"[{account_id}] 规格已生成，开始逐行填写 SKU 数据...")
        for i, sku in enumerate(skus_list):
            spec_name = sku.get("spec_name", "")
            print(f"[{account_id}] >>> 正在填写第 {i + 1} 个 SKU：[{spec_name}]")

            row = get_sku_row_by_spec(page, spec_name)
            if not row:
                print(f"[{account_id}] 未找到规格 [{spec_name}] 对应的价格表行，跳过")
                continue

            row.scroll.to_see()
            time.sleep(0.8)

            ok, input_count = fill_sku_row_inputs(row, sku)
            if not ok:
                print(
                    f"[{account_id}] 行内输入框不足 4 个（当前 {input_count} 个），跳过"
                )
                continue

            time.sleep(0.5)

            sku_img_name = sku.get("sku_image")
            if sku_img_name:
                try:
                    upload_input = row.ele("xpath:.//input[@type=\"file\"]", timeout=3)
                    if upload_input:
                        sku_img_path = os.path.abspath(os.path.join(asset_dir, sku_img_name))
                        if os.path.exists(sku_img_path):
                            upload_input.input(sku_img_path)
                            print(f"[{account_id}] 成功上传预览图: {sku_img_name}")
                            time.sleep(3.5)
                        else:
                            print(f"[{account_id}] 找不到本地图片: {sku_img_path}")
                    else:
                        print(f"[{account_id}] 未找到 [{spec_name}] 行的文件上传框")
                except Exception as img_e:
                    print(f"[{account_id}] 图片上传异常: {img_e}")

            print(f"[{account_id}] 第 {i + 1} 个 SKU ({spec_name}) 处理完成")

        print(f"[{account_id}] 寻找底部的全局商品编码...")
        global_product_code_input = page.ele(
            'xpath://span[contains(text(),"商品编码") or contains(text(),"货号")]/following::input[1]'
        )
        if global_product_code_input:
            global_product_code_input.input(listing_info.get("product_code", ""), clear=True)

        time.sleep(random.uniform(1.0, 2.0))

        print(f"[{account_id}] 点击提交并上架...")
        submit_btn = page.ele("text:提交并上架")
        if submit_btn:
            submit_btn.click()

        success_mark = page.ele("css:.success-title", timeout=10)
        if success_mark:
            print(f"[{account_id}] 成功：商品上架完毕")
        else:
            print(f"[{account_id}] 未检测到成功标志，请手动核查")

    except Exception as e:
        print(f"[{account_id}] 业务运行报错: {e}")
        try:
            page.get_screenshot(path=error_screenshot_path(f"error_trace_{account_id}.png"))
        except Exception:
            pass

    finally:
        time.sleep(2)
        page.quit()


def run_listing_job(config: dict):
    global_info = config.get("global_product_info", {})
    accounts_list = config.get("accounts", [])

    for account in accounts_list:
        if account.get("enabled"):
            process_single_account(account, global_info, config=config)
            print("\n等待 5 秒后切换下一个店铺任务...\n")
            time.sleep(5)
