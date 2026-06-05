"""多规格测试模式上架流程（款式 + 型号 + 预览图，支持多套图、多商品编码）。"""
import random
import time

from pdd_auto.ai.title import resolve_listing_title
from pdd_auto.browser.session import ensure_login
from pdd_auto.config import load_config
from pdd_auto.listing.multi_spec_helpers import (
    _safe_exc,
    add_style_and_model_specs,
    fill_multi_spec_rows,
    wait_multi_sku_rows,
)
from pdd_auto.listing.page_ai_title import apply_title_after_cover_upload
from pdd_auto.paths import chrome_profile_path, error_screenshot_path
from pdd_auto.products.multi_spec.catalog import (
    parse_all_listings,
    resolve_account_product_codes,
    validate_product,
)


def _print_product_summary(account_id: str, product):
    label = product.listing_label
    print(f"\n--- [{account_id}] 多规格商品：{label} ---")
    if product.image_set:
        print(f"[{account_id}] 套图：{product.image_set}")
    print(f"[{account_id}] 主图 {len(product.carousel_images)} 张，详情 {len(product.detail_images)} 张")
    print(f"[{account_id}] 款式({len(product.style_codes)})：{product.style_codes}")
    print(f"[{account_id}] 型号({len(product.model_codes)})：{product.model_codes}")
    print(f"[{account_id}] SKU 组合 {len(product.skus)} 个（页面款式/型号仅填中文名）：")
    for sku in product.skus:
        print(
            f"  · 款式={sku.style_name}  型号={sku.model_name}  "
            f"规格编码={sku.combo_folder}  预览={sku.preview_image.name}"
        )


def _upload_one_listing(page, account_id: str, product, product_info: dict, config: dict):
    """对单个套图/商品执行完整上架流程（浏览器已登录）。"""
    label = product.listing_label
    product_code = product.product_code
    covers = [str(p.resolve()) for p in product.carousel_images]
    details = [str(p.resolve()) for p in product.detail_images]
    defaults = (config.get("multi_spec") or {}).get("defaults") or {}
    style_names = list(dict.fromkeys(sku.style_name for sku in product.skus))
    model_names = list(dict.fromkeys(sku.model_name for sku in product.skus))
    print(f"[{account_id}] [{label}] 页面将录入款式：{style_names}")
    print(f"[{account_id}] [{label}] 页面将录入型号：{model_names}")

    listing_info = dict(product_info)
    listing_info["title"] = resolve_listing_title(
        product_info,
        account_id,
        product_path=str(product.root),
        config=config,
    )
    time.sleep(random.uniform(1.0, 2.0))

    print(f"[{account_id}] [{label}] 正在跳转商品分类界面...")
    page.get("https://mms.pinduoduo.com/goods/category")
    time.sleep(5)

    ui_type = "A"
    if page.ele("css:.goodsCarousel_btns__22KMn", timeout=1) or page.ele(
        'css:input[data-tracking-click-viewid="local_upload"]', timeout=1
    ):
        ui_type = "C"
    elif page.ele('css:[data-tracking-click-viewid="cate_tree_tab"]', timeout=1):
        ui_type = "B"
    print(f"[{account_id}] [{label}] 路由判定：分支 {ui_type}")

    if ui_type == "C":
        section_ele = page.ele("css:.goodsCarousel_btns__22KMn")
        if section_ele:
            page.run_js('arguments[0].style.display = "flex";', section_ele)
        time.sleep(1)
        cover_input = page.ele('css:input[data-tracking-click-viewid="local_upload"]')
        if cover_input:
            cover_input.input(covers)
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
            tab = page.ele('css:[data-tracking-click-viewid="cate_tree_tab"]')
            if tab:
                page.run_js("arguments[0].click();", tab)
                time.sleep(3)

        search_input = page.ele('css:input[placeholder="请输入关键词搜索分类"]')
        search_input.click()
        time.sleep(0.5)
        search_input.input(listing_info.get("category_keyword"), clear=True)
        time.sleep(2)
        first_cat = page.ele("css:li.SPP_searchItem_5-188-0")
        if first_cat:
            first_cat.click()
        time.sleep(1)
        confirm = page.ele("text:下一步, 完善商品信息") if ui_type == "B" else page.ele(
            "text:确认发布该类商品"
        )
        if confirm:
            confirm.click()
        time.sleep(5)
        page.wait.load_start()

        section_ele = page.ele("css:.uploadImgEnter.uploadImgEnterNew")
        if section_ele:
            page.run_js('arguments[0].style.display = "flex";', section_ele)
        time.sleep(1)
        cover_input = page.ele(
            'css:input[type="file"]:not([data-tracking-click-viewid="detail_img_localfile_upload"])'
        )
        if cover_input:
            cover_input.input(covers)
        time.sleep(random.uniform(1.5, 2.5))
        listing_info["title"] = apply_title_after_cover_upload(
            page, account_id, product_info, listing_info.get("title", "")
        )
        time.sleep(1)

    print(f"[{account_id}] [{label}] 正在上传详情图...")
    detail_input = page.ele(
        'css:input[data-tracking-click-viewid="detail_img_localfile_upload"]'
    )
    if detail_input and details:
        detail_input.input(details)
    time.sleep(2)

    print(f"[{account_id}] [{label}] 正在录入多规格（款式 + 型号）...")
    add_style_and_model_specs(page, account_id, style_names, model_names)
    time.sleep(1)
    sku_rows = wait_multi_sku_rows(page, account_id, product.skus)

    print(f"[{account_id}] [{label}] 开始填写价格表（库存/价格/规格编码/预览图）...")
    previews_ok = fill_multi_spec_rows(page, account_id, product.skus, defaults, rows=sku_rows)

    pcode = listing_info.get("product_code") or product_code
    if product.image_set:
        pcode = f"{pcode}-{product.image_set}"
    global_code = page.ele(
        'xpath://span[contains(text(),"商品编码") or contains(text(),"货号")]/following::input[1]'
    )
    if global_code:
        global_code.input(pcode, clear=True)

    time.sleep(random.uniform(1.0, 2.0))
    if not previews_ok:
        print(f"[{account_id}] [{label}] 预览图未全部就绪，跳过提交", flush=True)
        _clear_beforeunload(page)
        return
    _click_submit(page, account_id, label)
    _clear_beforeunload(page)


def _clear_beforeunload(page):
    """关闭「离开此网站」拦截，避免 quit 时弹出对话框导致控制台乱码。"""
    try:
        page.run_js("window.onbeforeunload = null;")
    except Exception:
        pass


def _click_submit(page, account_id: str, label: str) -> bool:
    print(f"[{account_id}] [{label}] 点击提交并上架...", flush=True)
    try:
        submit_btn = page.ele("text:提交并上架", timeout=3)
        if not submit_btn:
            print(f"[{account_id}] [{label}] 未找到「提交并上架」按钮", flush=True)
            return False
        submit_btn.click(by_js=True)
        time.sleep(2)
        if page.ele("css:.success-title", timeout=8):
            print(f"[{account_id}] [{label}] 成功：多规格商品上架完毕", flush=True)
            return True
        if page.ele("text:请上传预览图", timeout=1):
            print(f"[{account_id}] [{label}] 提交被拦截：仍有预览图未上传", flush=True)
            return False
        print(f"[{account_id}] [{label}] 未检测到成功标志，请手动核查", flush=True)
        return False
    except Exception as exc:
        print(f"[{account_id}] [{label}] 提交异常：{_safe_exc(exc)}", flush=True)
        return False


def _collect_valid_listings(
    account_id: str,
    product_codes: list[str],
    config: dict,
    log_fn,
) -> list:
    valid_listings = []
    for product_code in product_codes:
        try:
            listings = parse_all_listings(product_code, config, log=log_fn)
        except Exception as e:
            print(f"[{account_id}] 解析 [{product_code}] 异常：{e}")
            continue

        for product in listings:
            errors = validate_product(product)
            if errors:
                for err in errors:
                    print(f"[{account_id}] {err}")
                print(f"[{account_id}] [{product.listing_label}] 无可上架 SKU，跳过本套图")
                continue

            if product.warnings:
                print(
                    f"[{account_id}] [{product.listing_label}] "
                    f"解析有 {len(product.warnings)} 条警告（已跳过对应项）"
                )
            if not product.carousel_images:
                print(f"[{account_id}] [{product.listing_label}] [警告] 主图为空，仍将尝试上架")
            if not product.detail_images:
                print(f"[{account_id}] [{product.listing_label}] [警告] 详情图为空，仍将尝试上架")

            _print_product_summary(account_id, product)
            valid_listings.append(product)

    return valid_listings


def process_multi_spec_account(account_config, product_info, config=None, dry_run: bool = False):
    account_id = account_config.get("account_id")
    if config is None:
        config = load_config()

    product_codes = resolve_account_product_codes(account_config)
    if not product_codes:
        print(f"[{account_id}] 未选择商品编码，不发布新商品")
        return

    log_fn = lambda msg: print(f"[{account_id}] {msg}")
    print(f"[{account_id}] 已选商品编码：{product_codes}")

    valid_listings = _collect_valid_listings(account_id, product_codes, config, log_fn)

    if not valid_listings:
        print(f"[{account_id}] 所选商品均无有效套图可上架")
        return

    if dry_run:
        print(
            f"[{account_id}] dry-run：共 {len(valid_listings)} 个上架单元（套图），"
            f"不启动浏览器"
        )
        return

    username = account_config.get("username", "")
    password = account_config.get("password", "")

    page = ensure_login(account_id, chrome_profile_path(account_id), username, password)
    if not page:
        return

    try:
        for idx, product in enumerate(valid_listings):
            if idx > 0:
                print(
                    f"\n[{account_id}] 等待 5 秒后上架下一单元 [{product.listing_label}]...\n"
                )
                time.sleep(5)
            try:
                _upload_one_listing(page, account_id, product, product_info, config)
            except Exception as e:
                err = _safe_exc(e)
                print(f"[{account_id}] [{product.listing_label}] 业务运行报错: {err}")
                if "连接已断开" in err or "disconnect" in err.lower():
                    print(f"[{account_id}] 浏览器连接断开，停止后续上架", flush=True)
                    break
                try:
                    safe_set = (product.image_set or "default").replace("/", "_")
                    page.get_screenshot(
                        path=error_screenshot_path(
                            f"error_multi_spec_{account_id}_{product.product_code}_{safe_set}.png"
                        )
                    )
                except Exception:
                    pass
    finally:
        try:
            _clear_beforeunload(page)
        except Exception:
            pass
        time.sleep(2)
        page.quit()


def run_multi_spec_job(config: dict, dry_run: bool = False, product_code: str | None = None):
    global_info = config.get("global_product_info", {})
    accounts = config.get("accounts") or []

    for account in accounts:
        if not account.get("enabled"):
            continue
        if product_code:
            account = dict(account)
            account.setdefault("multi_spec", {})
            account["multi_spec"]["product_codes"] = [product_code]
        process_multi_spec_account(account, global_info, config=config, dry_run=dry_run)
        if not dry_run:
            print("\n等待 5 秒后切换下一个店铺...\n")
            time.sleep(5)
