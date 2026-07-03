"""
上架错误文案与 reason_code 常量。

改上架报错、飞书失败原因、跳过/失败分类，请只改本文件。
"""

from __future__ import annotations

import re
from typing import Any


class ListingErrorCode:
    """上架 reason_code 常量。"""

    # 上架前 / 素材
    PREFLIGHT_NO_SKUS = "preflight_no_skus"
    PREFLIGHT_NO_CAROUSEL = "preflight_no_carousel"
    PREFLIGHT_NO_DETAIL = "preflight_no_detail"
    PREFLIGHT_NO_MATERIAL = "preflight_no_material"
    PREFLIGHT_CATALOG = "preflight_catalog"
    COMBO_PREVIEW_NAMING_MISMATCH = "combo_preview_naming_mismatch"
    IMAGE_FILE_MISSING = "image_file_missing"
    CAROUSEL_IMAGE_DIMENSION_REJECTED = "carousel_image_dimension_rejected"
    PREVIEW_IMAGE_DIMENSION_REJECTED = "preview_image_dimension_rejected"
    CAROUSEL_IMAGE_FILE_SIZE_REJECTED = "carousel_image_file_size_rejected"
    PREVIEW_IMAGE_FILE_SIZE_REJECTED = "preview_image_file_size_rejected"
    CATALOG_PARSE_WARNING = "catalog_parse_warning"
    NO_VALID_UNITS = "no_valid_units"
    SLOT_ALIGNMENT_FAILED = "slot_alignment_failed"

    # 飞书商品表
    FEISHU_PRODUCT_CATALOG_MISSING = "feishu_product_catalog_missing"
    FEISHU_PRICING_MISSING = "feishu_pricing_missing"
    FEISHU_CONTROL_MISSING = "feishu_control_missing"
    FEISHU_PRICE_RANGE_MISSING = "feishu_price_range_missing"
    FEISHU_COLOR_SPEC_MISSING = "feishu_color_spec_missing"
    FEISHU_ROW_NOT_FOUND = "feishu_row_not_found"
    FEISHU_PRODUCT_ROW_MISSING = "feishu_product_row_missing"
    FEISHU_SUBCODE_MISSING = "feishu_subcode_missing"
    FEISHU_SUBCODE_PRICING_MISSING = "feishu_subcode_pricing_missing"
    FEISHU_SUBCODE_CONTROL_MISSING = "feishu_subcode_control_missing"
    FEISHU_SUBCODE_RANGE_MISSING = "feishu_subcode_range_missing"
    FEISHU_SUBCODE_COLOR_SPEC_MISSING = "feishu_subcode_color_spec_missing"

    # 页面填写 / 提交
    PREVIEW_NOT_READY = "preview_not_ready"
    PREVIEW_MISSING = "preview_missing"
    PLATFORM_LISTING_CODE_NOT_FILLED = "platform_listing_code_not_filled"
    PLATFORM_LISTING_CODE_VERIFY_FAILED = "platform_listing_code_verify_failed"
    VALIDATION_ERRORS = "validation_errors"
    VALIDATION_INCOMPLETE = "validation_incomplete"
    VALIDATION_REQUIRED = "validation_required"
    SUBMIT_BLOCKED = "submit_blocked"
    SUBMIT_UNCERTAIN = "submit_uncertain"
    SUBMIT_BUTTON_MISSING = "submit_button_missing"
    SUBMIT_EXCEPTION = "submit_exception"
    LISTED = "listed"
    REJECTED_AFTER_PUBLISH = "rejected_after_publish"
    PUBLISHED_BUT_NOT_FOUND = "published_but_not_found_in_on_sale_or_rejected"

    # 分类页 / 选类
    CATEGORY_NEXT_STEP_NO_ADVANCE = "category_next_step_no_advance"
    CATEGORY_NEXT_STEP_NOT_FOUND = "category_next_step_not_found"
    CATEGORY_RECOMMENDATION_MODAL_BLOCKING = "category_recommendation_modal_blocking"
    CATEGORY_SEARCH_FAILED = "category_search_failed"

    # 提交前设置（满件折扣 / 运费模板）
    PUBLISH_SETTINGS_INCOMPLETE = "publish_settings_incomplete"

    # 价格表
    PRICE_FILL_PARTIAL = "price_fill_partial"
    PRICE_FILL_ROW_NOT_FOUND = "price_fill_row_not_found"
    PRICE_FILL_BY_INDEX_FAILED = "price_fill_by_index_failed"

    # 浏览器 / 任务
    NEEDS_MANUAL_LOGIN_OR_CAPTCHA = "needs_manual_login_or_captcha"
    PAGE_OR_MATERIAL_CHANGED = "page_or_material_changed"
    BROWSER_TRANSIENT_ERROR = "browser_transient_error"
    BROWSER_MANUALLY_CLOSED = "browser_manually_closed"
    TASK_CANCELLED = "task_cancelled"
    USER_CANCELLED = "user_cancelled"
    UNEXPECTED_ERROR = "unexpected_error"


class ListingErrors:
    """上架错误：文案、模板、飞书/跳过/失败分类。"""

    DEFAULT_LABEL = "上架失败"
    FEISHU_RECORD_FAIL = "失败"
    FEISHU_RECORD_SKIP = "跳过"

    # 内部库 / 操作记录用（偏技术说明）
    LABELS: dict[str, str] = {
        ListingErrorCode.PREVIEW_NOT_READY: "预览图未全部上传，页面仍有规格行缺图",
        ListingErrorCode.PREVIEW_MISSING: "页面提示预览图缺失或未通过校验",
        ListingErrorCode.PLATFORM_LISTING_CODE_NOT_FILLED: "底部商品编码未填写",
        ListingErrorCode.PLATFORM_LISTING_CODE_VERIFY_FAILED: "底部商品编码与期望货号不一致",
        ListingErrorCode.VALIDATION_ERRORS: "提交前页面校验失败（库存/价格等未填完整）",
        ListingErrorCode.VALIDATION_INCOMPLETE: "提交前页面校验未通过（信息不完整）",
        ListingErrorCode.VALIDATION_REQUIRED: "提交前页面有必填项未处理",
        ListingErrorCode.SUBMIT_BLOCKED: "点击提交被页面拦截（通常仍有红色错误项）",
        ListingErrorCode.SUBMIT_UNCERTAIN: "提交结果不确定，需人工到在售/驳回列表核对",
        ListingErrorCode.SUBMIT_BUTTON_MISSING: "未找到「提交并上架」按钮",
        ListingErrorCode.SUBMIT_EXCEPTION: "点击提交时发生异常",
        ListingErrorCode.LISTED: "已提交但后续抓取商品 ID 失败",
        ListingErrorCode.REJECTED_AFTER_PUBLISH: "提交后被平台驳回",
        ListingErrorCode.PUBLISHED_BUT_NOT_FOUND: "提交后未在售列表/驳回列表中找到商品",
        ListingErrorCode.CATEGORY_NEXT_STEP_NO_ADVANCE: "分类页点下一步后未进入商品详情",
        ListingErrorCode.CATEGORY_NEXT_STEP_NOT_FOUND: "分类页未找到「下一步」按钮",
        ListingErrorCode.CATEGORY_RECOMMENDATION_MODAL_BLOCKING: "推荐分类弹窗未确认，无法点下一步",
        ListingErrorCode.CATEGORY_SEARCH_FAILED: "分类搜索失败，未选到类目",
        ListingErrorCode.PUBLISH_SETTINGS_INCOMPLETE: "提交前满件折扣或运费模板未设置成功",
        ListingErrorCode.NEEDS_MANUAL_LOGIN_OR_CAPTCHA: "需要人工登录或处理验证码/滑块",
        ListingErrorCode.PAGE_OR_MATERIAL_CHANGED: "页面结构或素材异常（分类/规格/上传相关）",
        ListingErrorCode.BROWSER_TRANSIENT_ERROR: "浏览器超时或连接断开",
        ListingErrorCode.UNEXPECTED_ERROR: "未分类的运行异常",
        ListingErrorCode.PREFLIGHT_NO_SKUS: "上架前校验：无有效 SKU",
        ListingErrorCode.PREFLIGHT_NO_CAROUSEL: "上架前校验：主图为空",
        ListingErrorCode.PREFLIGHT_NO_DETAIL: "上架前校验：详情图为空",
        ListingErrorCode.PREFLIGHT_NO_MATERIAL: "上架前校验：商品素材图为空",
        ListingErrorCode.PREFLIGHT_CATALOG: "上架前校验：商品表或素材目录问题",
        ListingErrorCode.COMBO_PREVIEW_NAMING_MISMATCH: "组合图文件名未以文件夹名开头",
        ListingErrorCode.IMAGE_FILE_MISSING: "图片文件不存在或无法读取",
        ListingErrorCode.CAROUSEL_IMAGE_DIMENSION_REJECTED: "主图尺寸不符合平台要求",
        ListingErrorCode.PREVIEW_IMAGE_DIMENSION_REJECTED: "预览图尺寸不符合平台要求",
        ListingErrorCode.CAROUSEL_IMAGE_FILE_SIZE_REJECTED: "主图大小不能超过3MB",
        ListingErrorCode.PREVIEW_IMAGE_FILE_SIZE_REJECTED: "预览图大小不能超过3MB",
        ListingErrorCode.PRICE_FILL_PARTIAL: "价格表文字字段未全部填写（库存/拼团价/单买价/编码）",
        ListingErrorCode.PRICE_FILL_ROW_NOT_FOUND: "价格表找不到对应规格行",
        ListingErrorCode.PRICE_FILL_BY_INDEX_FAILED: "按行号填写价格表失败",
        ListingErrorCode.CATALOG_PARSE_WARNING: "素材目录解析警告",
        ListingErrorCode.NO_VALID_UNITS: "无有效上架单元",
        ListingErrorCode.SLOT_ALIGNMENT_FAILED: "兄弟款规格数量不一致",
        ListingErrorCode.FEISHU_PRODUCT_CATALOG_MISSING: "飞书商品/定价数据缺失",
        ListingErrorCode.FEISHU_PRICING_MISSING: "定价数据缺失",
        ListingErrorCode.FEISHU_CONTROL_MISSING: "控价数据缺失",
        ListingErrorCode.FEISHU_PRICE_RANGE_MISSING: "控价区间数据缺失",
        ListingErrorCode.FEISHU_COLOR_SPEC_MISSING: "颜色规格没数据",
        ListingErrorCode.FEISHU_ROW_NOT_FOUND: "飞书无此行",
        ListingErrorCode.FEISHU_PRODUCT_ROW_MISSING: "飞书无此行",
        ListingErrorCode.FEISHU_SUBCODE_MISSING: "飞书无子编码",
        ListingErrorCode.FEISHU_SUBCODE_PRICING_MISSING: "子编码定价数据缺失",
        ListingErrorCode.FEISHU_SUBCODE_CONTROL_MISSING: "子编码控价数据缺失",
        ListingErrorCode.FEISHU_SUBCODE_RANGE_MISSING: "子编码控价区间数据缺失",
        ListingErrorCode.FEISHU_SUBCODE_COLOR_SPEC_MISSING: "子编码颜色规格没数据",
        ListingErrorCode.TASK_CANCELLED: "任务已被用户停止",
        ListingErrorCode.USER_CANCELLED: "任务已被用户停止",
        ListingErrorCode.BROWSER_MANUALLY_CLOSED: "浏览器被手动关闭，任务中断",
    }

    # 飞书失败表一行说明（极短，带商品编码，给运营直接找文件；不含平台名）
    FEISHU_BRIEF_ASPECT: dict[str, str] = {
        "pricing_missing": "定价为空",
        "control_missing": "控价为空",
        "range_missing": "零售综合成本为空",
        "range_retail_cost_missing": "零售综合成本为空",
        "range_min_missing": "零售综合成本为空",
        "range_max_missing": "零售综合成本为空",
        "color_spec_missing": "颜色规格为空",
        "feishu_row_not_found": "飞书无此行",
        "product_row_missing": "飞书无此行",
        "subcode_missing": "飞书无此行",
    }

    # 组合图失败表：{母编码}下子图{组合图文件名}的{字段}为空
    FEISHU_COMBO_FIELD_NAME: dict[str, str] = {
        "pricing_missing": "定价",
        "control_missing": "控价",
        "range_missing": "零售综合成本",
        "range_retail_cost_missing": "零售综合成本",
        "range_min_missing": "零售综合成本",
        "range_max_missing": "零售综合成本",
        "color_spec_missing": "颜色规格",
    }

    FEISHU_BRIEF_ASPECT_TEXT: dict[str, str] = {
        "定价数据缺失": "定价为空",
        "定价没数据": "定价为空",
        "控价数据缺失": "控价为空",
        "控价没数据": "控价为空",
        "控价区间数据缺失": "控价下限或上限为空",
        "控价区间没数据": "控价下限或上限为空",
        "PDD控价下限数据缺失": "控价下限为空",
        "PDD控价下限没数据": "控价下限为空",
        "PDD控价上限数据缺失": "控价上限为空",
        "PDD控价上限没数据": "控价上限为空",
        "颜色规格没数据": "颜色规格为空",
        "飞书无此行": "飞书无此行",
        "商品表没数据": "飞书无此行",
        "商品表为空": "飞书无此行",
        "商品表数据缺失": "飞书无此行",
        "没数据": "飞书无此行",
        "飞书数据缺失": "飞书无此行",
    }

    # 飞书「淘宝+拼多多发布日志表（失败）」通用短句（无编码前缀时）
    FEISHU_LABELS: dict[str, str] = {
        ListingErrorCode.PREVIEW_NOT_READY: "预览图还没全部上传完，暂不能提交",
        ListingErrorCode.PREVIEW_MISSING: "页面提示还有预览图没上传",
        ListingErrorCode.PLATFORM_LISTING_CODE_NOT_FILLED: "底部商品编码没填",
        ListingErrorCode.PLATFORM_LISTING_CODE_VERIFY_FAILED: "底部商品编码与货号不一致",
        ListingErrorCode.VALIDATION_ERRORS: "页面还有红色错误项没改完",
        ListingErrorCode.VALIDATION_INCOMPLETE: "页面提示信息未填完整",
        ListingErrorCode.VALIDATION_REQUIRED: "页面还有必填项没填",
        ListingErrorCode.SUBMIT_BLOCKED: "点击提交被页面拦住",
        ListingErrorCode.SUBMIT_UNCERTAIN: "提交结果不确定，请到拼多多后台核对",
        ListingErrorCode.SUBMIT_BUTTON_MISSING: "找不到「提交并上架」按钮",
        ListingErrorCode.SUBMIT_EXCEPTION: "点击提交时出错",
        ListingErrorCode.LISTED: "已提交但未抓到商品 ID",
        ListingErrorCode.REJECTED_AFTER_PUBLISH: "提交后在「已驳回」找到商品，平台已驳回",
        ListingErrorCode.PUBLISHED_BUT_NOT_FOUND: "提交后在在售/驳回列表没找到刚上的商品，请人工核对",
        ListingErrorCode.CATEGORY_NEXT_STEP_NO_ADVANCE: "分类页点下一步后未进入商品详情",
        ListingErrorCode.CATEGORY_NEXT_STEP_NOT_FOUND: "分类页未找到「下一步」按钮",
        ListingErrorCode.CATEGORY_RECOMMENDATION_MODAL_BLOCKING: "推荐分类弹窗未确认，无法点下一步",
        ListingErrorCode.CATEGORY_SEARCH_FAILED: "分类搜索失败，未选到类目",
        ListingErrorCode.PUBLISH_SETTINGS_INCOMPLETE: "提交前满件折扣或运费模板未设置成功",
        ListingErrorCode.NEEDS_MANUAL_LOGIN_OR_CAPTCHA: "需要人工处理验证码或重新登录",
        ListingErrorCode.PAGE_OR_MATERIAL_CHANGED: "页面或素材异常（分类/规格/上传相关）",
        ListingErrorCode.BROWSER_TRANSIENT_ERROR: "浏览器超时或断连，可重试",
        ListingErrorCode.BROWSER_MANUALLY_CLOSED: "浏览器被手动关闭，任务中断",
        ListingErrorCode.UNEXPECTED_ERROR: "运行异常，请查看操作记录",
        ListingErrorCode.PREFLIGHT_NO_SKUS: "Excel 与预览图对不上，没有可上架规格",
        ListingErrorCode.PREFLIGHT_NO_CAROUSEL: "缺少主图（需 1-5 编号图）",
        ListingErrorCode.PREFLIGHT_NO_DETAIL: "缺少详情图（需 6-8 编号图）",
        ListingErrorCode.PREFLIGHT_NO_MATERIAL: "缺少商品素材图（需 9 编号图）",
        ListingErrorCode.PREFLIGHT_CATALOG: "商品目录或素材有问题",
        ListingErrorCode.COMBO_PREVIEW_NAMING_MISMATCH: "组合图文件名未以文件夹名开头",
        ListingErrorCode.IMAGE_FILE_MISSING: "图片文件不存在或打不开",
        ListingErrorCode.CAROUSEL_IMAGE_DIMENSION_REJECTED: "主图尺寸不符合要求",
        ListingErrorCode.PREVIEW_IMAGE_DIMENSION_REJECTED: "预览图尺寸不符合要求",
        ListingErrorCode.CAROUSEL_IMAGE_FILE_SIZE_REJECTED: "主图大小不能超过3MB",
        ListingErrorCode.PREVIEW_IMAGE_FILE_SIZE_REJECTED: "预览图大小不能超过3MB",
        ListingErrorCode.PRICE_FILL_PARTIAL: "价格表没填完整（库存/拼团价/单买价/编码）",
        ListingErrorCode.PRICE_FILL_ROW_NOT_FOUND: "价格表找不到对应规格行",
        ListingErrorCode.PRICE_FILL_BY_INDEX_FAILED: "按行号填写价格表失败",
        ListingErrorCode.CATALOG_PARSE_WARNING: "素材目录解析有问题",
        ListingErrorCode.NO_VALID_UNITS: "没有可上架的套图（素材或校验未通过）",
        ListingErrorCode.SLOT_ALIGNMENT_FAILED: "兄弟款规格数量不一致",
        ListingErrorCode.TASK_CANCELLED: "任务已被用户停止",
        ListingErrorCode.USER_CANCELLED: "任务已被用户停止",
        ListingErrorCode.FEISHU_PRODUCT_CATALOG_MISSING: "飞书商品/定价数据缺失",
        ListingErrorCode.FEISHU_PRICING_MISSING: "定价数据缺失",
        ListingErrorCode.FEISHU_CONTROL_MISSING: "控价数据缺失",
        ListingErrorCode.FEISHU_PRICE_RANGE_MISSING: "控价区间数据缺失",
        ListingErrorCode.FEISHU_COLOR_SPEC_MISSING: "颜色规格没数据",
        ListingErrorCode.FEISHU_ROW_NOT_FOUND: "飞书无此行",
        ListingErrorCode.FEISHU_PRODUCT_ROW_MISSING: "飞书无此行",
        ListingErrorCode.FEISHU_SUBCODE_MISSING: "飞书无子编码",
        ListingErrorCode.FEISHU_SUBCODE_PRICING_MISSING: "子编码定价数据缺失",
        ListingErrorCode.FEISHU_SUBCODE_CONTROL_MISSING: "子编码控价数据缺失",
        ListingErrorCode.FEISHU_SUBCODE_RANGE_MISSING: "子编码控价区间数据缺失",
        ListingErrorCode.FEISHU_SUBCODE_COLOR_SPEC_MISSING: "子编码颜色规格没数据",
    }

    # 飞书 humanize 时按原文匹配的补充文案（无独立 reason_code）
    FEISHU_HUMANIZE_EXTRA: dict[str, str] = {
        "catalog_dir_missing": "找不到商品目录或套图文件夹",
        "numbered_images_missing": "缺少按数字命名的图片",
        "preview_image_missing": "缺少规格预览图",
        "page_action_timeout": "页面操作等待超时",
    }

    # 飞书商品表缺项：aspect → (reason_code, 缺项说明)
    FEISHU_CATALOG_ASPECT: dict[str, tuple[str, str]] = {
        "pricing_missing": (ListingErrorCode.FEISHU_PRICING_MISSING, "拼多多定价没数据"),
        "control_missing": (ListingErrorCode.FEISHU_CONTROL_MISSING, "拼多多控价没数据"),
        "range_missing": (ListingErrorCode.FEISHU_PRICE_RANGE_MISSING, "零售综合成本没数据"),
        "range_retail_cost_missing": (ListingErrorCode.FEISHU_PRICE_RANGE_MISSING, "零售综合成本没数据"),
        "range_min_missing": (ListingErrorCode.FEISHU_PRICE_RANGE_MISSING, "零售综合成本没数据"),
        "range_max_missing": (ListingErrorCode.FEISHU_PRICE_RANGE_MISSING, "零售综合成本没数据"),
        "color_spec_missing": (ListingErrorCode.FEISHU_COLOR_SPEC_MISSING, "颜色规格没数据"),
        "feishu_row_not_found": (ListingErrorCode.FEISHU_ROW_NOT_FOUND, "飞书无此行"),
        "product_row_missing": (ListingErrorCode.FEISHU_ROW_NOT_FOUND, "飞书无此行"),
        "subcode_missing": (ListingErrorCode.FEISHU_SUBCODE_MISSING, "飞书无子编码"),
    }

    FEISHU_CATALOG_SUB_ASPECT: dict[str, str] = {
        "pricing_missing": ListingErrorCode.FEISHU_SUBCODE_PRICING_MISSING,
        "control_missing": ListingErrorCode.FEISHU_SUBCODE_CONTROL_MISSING,
        "range_missing": ListingErrorCode.FEISHU_SUBCODE_RANGE_MISSING,
        "range_retail_cost_missing": ListingErrorCode.FEISHU_SUBCODE_RANGE_MISSING,
        "range_min_missing": ListingErrorCode.FEISHU_SUBCODE_RANGE_MISSING,
        "range_max_missing": ListingErrorCode.FEISHU_SUBCODE_RANGE_MISSING,
        "color_spec_missing": ListingErrorCode.FEISHU_SUBCODE_COLOR_SPEC_MISSING,
        "feishu_row_not_found": ListingErrorCode.FEISHU_SUBCODE_MISSING,
        "product_row_missing": ListingErrorCode.FEISHU_SUBCODE_MISSING,
        "subcode_missing": ListingErrorCode.FEISHU_SUBCODE_MISSING,
    }

    # 诊断摘要用短标签（code_details 展示）
    FEISHU_CATALOG_ASPECT_SHORT: dict[str, str] = {
        "pricing_missing": "拼多多定价没数据",
        "control_missing": "拼多多控价没数据",
        "range_missing": "零售综合成本没数据",
        "range_retail_cost_missing": "零售综合成本没数据",
        "range_min_missing": "零售综合成本没数据",
        "range_max_missing": "零售综合成本没数据",
        "color_spec_missing": "颜色规格没数据",
        "feishu_row_not_found": "飞书无此行",
        "product_row_missing": "飞书无此行",
        "subcode_missing": "飞书无子编码",
    }

    # 提交页拦截检测：页面文案片段 → reason_code
    SUBMIT_BLOCK_DETECTORS: tuple[tuple[str, str], ...] = (
        ("text:错误项未处理", ListingErrorCode.VALIDATION_ERRORS),
        ("text:个错误项", ListingErrorCode.VALIDATION_ERRORS),
        ("text:请完善", ListingErrorCode.VALIDATION_INCOMPLETE),
        ("text:请填写", ListingErrorCode.VALIDATION_REQUIRED),
        ("text:不能为空", ListingErrorCode.VALIDATION_REQUIRED),
    )

    SUBMIT_BLOCK_LOG: dict[str, str] = {
        ListingErrorCode.VALIDATION_ERRORS: "提交被拦截：页面仍有错误项未处理",
        ListingErrorCode.VALIDATION_INCOMPLETE: "提交被拦截：页面提示请完善信息",
        ListingErrorCode.VALIDATION_REQUIRED: "提交被拦截：页面仍有必填项未填写",
    }

    VALIDATION_DETAIL_REASON_CODES: frozenset[str] = frozenset(
        {
            ListingErrorCode.VALIDATION_ERRORS,
            ListingErrorCode.VALIDATION_INCOMPLETE,
            ListingErrorCode.VALIDATION_REQUIRED,
            ListingErrorCode.SUBMIT_BLOCKED,
            ListingErrorCode.PREVIEW_NOT_READY,
            ListingErrorCode.PREVIEW_MISSING,
            ListingErrorCode.PRICE_FILL_PARTIAL,
            ListingErrorCode.CATEGORY_NEXT_STEP_NO_ADVANCE,
            ListingErrorCode.CATEGORY_NEXT_STEP_NOT_FOUND,
            ListingErrorCode.CATEGORY_RECOMMENDATION_MODAL_BLOCKING,
            ListingErrorCode.CATEGORY_SEARCH_FAILED,
            ListingErrorCode.PUBLISH_SETTINGS_INCOMPLETE,
        }
    )

    SKIP_REASON_CODES: frozenset[str] = frozenset(
        {
            ListingErrorCode.SLOT_ALIGNMENT_FAILED,
            ListingErrorCode.PREFLIGHT_NO_SKUS,
            ListingErrorCode.PREFLIGHT_NO_CAROUSEL,
            ListingErrorCode.PREFLIGHT_NO_DETAIL,
            ListingErrorCode.PREFLIGHT_NO_MATERIAL,
            ListingErrorCode.PREFLIGHT_CATALOG,
            ListingErrorCode.COMBO_PREVIEW_NAMING_MISMATCH,
            ListingErrorCode.CATALOG_PARSE_WARNING,
            ListingErrorCode.NO_VALID_UNITS,
            ListingErrorCode.IMAGE_FILE_MISSING,
        }
    )

    FAIL_REASON_CODES: frozenset[str] = frozenset(
        {
            ListingErrorCode.REJECTED_AFTER_PUBLISH,
            ListingErrorCode.PUBLISHED_BUT_NOT_FOUND,
            ListingErrorCode.SUBMIT_UNCERTAIN,
            ListingErrorCode.SUBMIT_BLOCKED,
            ListingErrorCode.SUBMIT_EXCEPTION,
            ListingErrorCode.SUBMIT_BUTTON_MISSING,
            ListingErrorCode.PREVIEW_NOT_READY,
            ListingErrorCode.PREVIEW_MISSING,
            ListingErrorCode.VALIDATION_ERRORS,
            ListingErrorCode.VALIDATION_INCOMPLETE,
            ListingErrorCode.VALIDATION_REQUIRED,
            ListingErrorCode.PLATFORM_LISTING_CODE_NOT_FILLED,
            ListingErrorCode.PLATFORM_LISTING_CODE_VERIFY_FAILED,
            ListingErrorCode.NEEDS_MANUAL_LOGIN_OR_CAPTCHA,
            ListingErrorCode.BROWSER_TRANSIENT_ERROR,
            ListingErrorCode.BROWSER_MANUALLY_CLOSED,
            ListingErrorCode.PAGE_OR_MATERIAL_CHANGED,
            ListingErrorCode.UNEXPECTED_ERROR,
            ListingErrorCode.PRICE_FILL_PARTIAL,
            ListingErrorCode.PRICE_FILL_ROW_NOT_FOUND,
            ListingErrorCode.PRICE_FILL_BY_INDEX_FAILED,
            ListingErrorCode.LISTED,
            ListingErrorCode.CAROUSEL_IMAGE_DIMENSION_REJECTED,
            ListingErrorCode.PREVIEW_IMAGE_DIMENSION_REJECTED,
            ListingErrorCode.CAROUSEL_IMAGE_FILE_SIZE_REJECTED,
            ListingErrorCode.PREVIEW_IMAGE_FILE_SIZE_REJECTED,
            ListingErrorCode.FEISHU_PRODUCT_CATALOG_MISSING,
        }
    )

    RETRYABLE_REASON_CODES: frozenset[str] = frozenset(
        {
            ListingErrorCode.PREVIEW_NOT_READY,
            ListingErrorCode.PREVIEW_MISSING,
            ListingErrorCode.PLATFORM_LISTING_CODE_NOT_FILLED,
            ListingErrorCode.PLATFORM_LISTING_CODE_VERIFY_FAILED,
            ListingErrorCode.VALIDATION_ERRORS,
            ListingErrorCode.VALIDATION_INCOMPLETE,
            ListingErrorCode.VALIDATION_REQUIRED,
            ListingErrorCode.SUBMIT_BLOCKED,
            ListingErrorCode.SUBMIT_UNCERTAIN,
            ListingErrorCode.SUBMIT_BUTTON_MISSING,
            ListingErrorCode.SUBMIT_EXCEPTION,
            ListingErrorCode.LISTED,
            ListingErrorCode.PUBLISHED_BUT_NOT_FOUND,
            ListingErrorCode.NEEDS_MANUAL_LOGIN_OR_CAPTCHA,
            ListingErrorCode.PAGE_OR_MATERIAL_CHANGED,
            ListingErrorCode.BROWSER_TRANSIENT_ERROR,
            ListingErrorCode.UNEXPECTED_ERROR,
            ListingErrorCode.PREFLIGHT_NO_SKUS,
            ListingErrorCode.PREFLIGHT_NO_CAROUSEL,
            ListingErrorCode.PREFLIGHT_NO_DETAIL,
            ListingErrorCode.PREFLIGHT_NO_MATERIAL,
            ListingErrorCode.PREFLIGHT_CATALOG,
            ListingErrorCode.IMAGE_FILE_MISSING,
            ListingErrorCode.PRICE_FILL_PARTIAL,
            ListingErrorCode.PRICE_FILL_ROW_NOT_FOUND,
            ListingErrorCode.PRICE_FILL_BY_INDEX_FAILED,
            ListingErrorCode.CATALOG_PARSE_WARNING,
            ListingErrorCode.NO_VALID_UNITS,
            ListingErrorCode.SLOT_ALIGNMENT_FAILED,
        }
    )

    class Msg:
        """带变量的动态报错模板。"""

        # preflight / catalog
        CATALOG_DIR_MISSING = "商品目录不存在或无套图: {code}"
        CAROUSEL_EMPTY = "主图为空"
        DETAIL_EMPTY = "详情图为空"
        NO_VALID_SKU = "未解析到任何有效 SKU"
        CAROUSEL_MISSING = "[{label}] 未找到 1-5 主图"
        DETAIL_MISSING = "[{label}] 未找到 6-8 详情图"
        MATERIAL_MISSING = "[{label}] 未找到 9 商品素材图"
        MATERIAL_EMPTY = "商品素材图为空"
        FEISHU_MATERIAL_MISSING = "{code}商品素材图缺失"
        NO_SKU_PARSED = "[{label}] 未解析到任何有效 SKU"
        PREVIEW_MISSING = "[{label}] 缺少预览图: {style}/{combo}"
        STYLE_CODE_MISSING_SKIP = "[{label}] 商品表无款式编码[{style}]，跳过"
        COMBO_FOLDER_INVALID = "[{label}] 组合文件夹格式错误: {folder}"
        MODEL_CODE_MISSING_SKIP = "[{label}] 商品表无型号编码[{model}]，跳过"
        PREVIEW_FILENAME_UNPARSEABLE = "{prefix} 规格图文件名无法解析组合编码: {name}"
        STYLE_NOT_IN_CATALOG_SKIP = "{prefix} 商品表无编码[{style}]，不上架 {name}"
        STYLE_NOT_IN_CATALOG_WARN = "{prefix} 商品表无款式编码[{style}]，不上架 {name}"
        STYLE_NOT_IN_CATALOG_DISPLAY = "{prefix} 商品表无款式编码[{style}]，仅后台展示不上架 {name}"
        SUBCODE_NOT_IN_CATALOG_SKIP = "{prefix} 组合图[{combo}]商品表无子编码[{model}]，不上架 {name}"
        SUBCODE_NOT_IN_CATALOG_DISPLAY = "{prefix} 组合图[{combo}]商品表无子编码[{model}]，仅后台展示不上架 {name}"
        CATALOG_CODE_PRICING_MISSING = "{prefix} 商品表无编码[{codes}]，无法定价"
        CATALOG_CODE_PRICING_MISSING_COMBO = "{prefix} 组合图[{combo}]商品表无编码[{codes}]，无法定价"
        CATALOG_PRICING_INVALID = "{prefix} 商品表编码[{codes}]拼多多定价无效"
        CATALOG_PRICING_INVALID_COMBO = "{prefix} 组合图[{combo}]商品表编码[{codes}]拼多多定价无效"
        NO_NUMBERED_IMAGES = "无任何数字命名图 ({range})"

        # 兄弟款规格
        SLOT_MISMATCH = "兄弟款规格不齐：{detail}（应为{target}个）"
        SLOT_MISMATCH_MISNAMED_PREVIEW = "兄弟款规格图命名错误：{detail}（应为{target}个）"
        SLOT_MISMATCH_FALLBACK = "兄弟款规格不齐：{code}（主款{reference}{count}个）"
        SLOT_PREFIX = "兄弟款规格不齐："
        SLOT_MISNAMED_PREFIX = "兄弟款规格图命名错误："

        # 槽位对齐（旧格式兼容）
        SLOT_NO_STYLE = "[{label}] 无有效款式编码"
        SLOT_REF_NO_SKU = "[{label}] 主款 {reference} 无 SKU"
        SLOT_COUNT_ABNORMAL = "[{label}] 槽位对齐后 SKU 数异常：期望 {expected}，实际 {actual}"
        SLOT_SIGNATURE_MISMATCH = (
            "[{label}] 槽位对齐签名未命中：{code} 的 {combo}（签名 {signature}）"
        )

        # 飞书失败表（编码+短说明，不含套图路径/子编码字样）
        FEISHU_CATALOG_LINE = "{code}{aspect}"
        FEISHU_SLOT_LINE = "{detail}"
        FEISHU_IMAGES_MISSING = "图片缺失 {nums}"
        FEISHU_CAROUSEL_MISSING = "{code}主图缺失"
        FEISHU_DETAIL_MISSING = "{code}详情图缺失"

        # 上传 / 提交
        PREVIEW_VERIFY_DETAIL = (
            "预览图页面校验 {verified}/{need}，上传成功 {uploaded}/{need}"
        )
        IMAGE_FILE_BAD = "图片无法打开或不存在（{kind}）"
        PRICE_FILL_PARTIAL = "价格表仅填写 {filled}/{total} 行，其余行库存/价格/编码未写入"
        SUBMIT_SUCCESS_NO_CAPTURE = "提交成功页已出现，但商品列表未匹配到本次发布记录"
        NO_VALID_UNITS_SUMMARY = "没有通过校验的上架单元"
        UNKNOWN_ACCOUNT = "unknown account: {account_id}"

        # 飞书 humanize 补充
        NUMBERED_IMAGES_SUFFIX = "缺少按数字命名的图片 ({detail})"
        PREVIEW_IMAGE_SUFFIX = "缺少规格预览图（{detail}）"

    @classmethod
    def format_validation_detail_brief(
        cls,
        issues: list[str],
        *,
        merchant_code: str = "",
        max_items: int = 4,
    ) -> str:
        """把缺项列表压成飞书一行说明；无具体项时返回空串。"""
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in issues:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        if not cleaned:
            return ""
        code = str(merchant_code or "").strip().upper()
        body = cls.format_numbered(cleaned[: max(1, int(max_items))])
        if len(cleaned) > max_items:
            body = f"{body}等{len(cleaned)}项"
        if code and not body.startswith(code):
            return cls.sanitize_feishu_failure_reason(f"{code}{body}")[:500]
        return cls.sanitize_feishu_failure_reason(body)[:500]

    @classmethod
    def label(cls, reason_code: str, *, fallback: str = "") -> str:
        code = str(reason_code or "").strip()
        return cls.LABELS.get(code, fallback or code or cls.DEFAULT_LABEL)

    @classmethod
    def feishu_label(cls, reason_code: str, *, fallback: str = "") -> str:
        code = str(reason_code or "").strip()
        return cls.FEISHU_LABELS.get(code, fallback or code or cls.DEFAULT_LABEL)

    @classmethod
    def sanitize_feishu_failure_reason(cls, text: str) -> str:
        """飞书失败原因：去掉平台字样（拼多多/PDD/pdd），所属平台列已单独记录。"""
        s = str(text or "").strip()
        if not s:
            return s
        s = s.replace("拼多多", "")
        s = re.sub(r"(?i)pdd", "", s)
        return s

    @classmethod
    def compact_system_diagnostic(cls, text: str) -> str:
        """系统原因：去掉 [套图路径][来源目录] 等前缀，保留具体诊断句。"""
        raw = str(text or "").strip()
        while raw.startswith("[") and "]" in raw:
            raw = raw.split("]", 1)[-1].strip(" :：")
        return raw

    @classmethod
    def _extract_merchant_from_prefix(cls, text: str) -> str:
        matched = re.match(r"^\[([^/\]]+)", str(text or "").strip())
        if not matched:
            return ""
        return str(matched.group(1) or "").strip().upper()

    @classmethod
    def feishu_combo_subimage_line(
        cls,
        main_code: str,
        combo_stem: str,
        aspect: str,
    ) -> str:
        """飞书失败表：母商品编码 + 组合图文件名 + 缺失字段。"""
        main = str(main_code or "").strip().upper()
        combo = str(combo_stem or "").strip()
        if not main or not combo:
            return ""
        if aspect in {"feishu_row_not_found", "product_row_missing", "subcode_missing"}:
            return cls.sanitize_feishu_failure_reason(f"{main}下子图{combo}飞书无此行")
        field = cls.FEISHU_COMBO_FIELD_NAME.get(aspect, "")
        if field:
            return cls.sanitize_feishu_failure_reason(f"{main}下子图{combo}的{field}为空")
        suffix = cls.FEISHU_BRIEF_ASPECT.get(aspect, "数据为空")
        return cls.sanitize_feishu_failure_reason(f"{main}下子图{combo}的{suffix}")

    @classmethod
    def _catalog_warning_to_brief(cls, text: str) -> str:
        """从商品表/定价类 warning 提取「编码+具体问题」简述。"""
        raw = str(text or "").strip()
        clean = cls.compact_system_diagnostic(raw)
        if not clean:
            return ""
        merchant = cls._extract_merchant_from_prefix(raw)

        combo_patterns: list[tuple[str, str]] = [
            (r"组合图\[([^\]]+)\].*商品表编码\[([^\]]+)\].*定价无效", "pricing_missing"),
            (r"组合图\[([^\]]+)\].*商品表无编码\[([^\]]+)\].*无法定价", "pricing_missing"),
            (r"组合图\[([^\]]+)\].*商品表无子编码\[([^\]]+)\]", "feishu_row_not_found"),
        ]
        for pattern, aspect in combo_patterns:
            matched = re.search(pattern, clean)
            if not matched:
                continue
            combo = str(matched.group(1) or "").strip()
            if merchant and combo:
                return cls.feishu_combo_subimage_line(merchant, combo, aspect)

        patterns: list[tuple[str, str]] = [
            (r"商品表无子编码\[([^\]]+)\]", "feishu_row_not_found"),
            (r"商品表编码\[([^\]]+)\].*定价无效", "pricing_missing"),
            (r"商品表无编码\[([^\]]+)\].*无法定价", "pricing_missing"),
            (r"商品表无编码\[([^\]]+)\]", "feishu_row_not_found"),
            (r"商品表无款式编码\[([^\]]+)\]", "feishu_row_not_found"),
        ]
        for pattern, aspect in patterns:
            matched = re.search(pattern, clean)
            if not matched:
                continue
            raw_codes = str(matched.group(1) or "").strip()
            code = raw_codes.split("、")[0].strip().upper()
            if not code:
                continue
            if merchant and code != merchant:
                return cls.feishu_combo_subimage_line(merchant, code, aspect)
            return cls.feishu_catalog_line(code, aspect)
        return ""

    @classmethod
    def _unit_warnings_for_label(cls, preflight: Any, listing_label: str) -> list[str]:
        label = str(listing_label or "").strip()
        if not label:
            return []
        units: list[Any] = []
        if isinstance(preflight, dict):
            units = list(preflight.get("units") or [])
        elif preflight is not None:
            units = list(getattr(preflight, "units", None) or [])
        for unit in units:
            unit_label = str(
                getattr(unit, "listing_label", None)
                or (unit.get("listing_label") if isinstance(unit, dict) else "")
                or ""
            ).strip()
            if unit_label != label:
                continue
            warnings = getattr(unit, "warnings", None) or (
                unit.get("warnings") if isinstance(unit, dict) else []
            ) or []
            return [str(item or "") for item in warnings if str(item or "").strip()]
        return []

    @classmethod
    def infer_no_sku_failure_brief(
        cls,
        *,
        preflight: Any = None,
        listing_label: str = "",
        merchant_code: str = "",
        fallback_message: str = "",
    ) -> str:
        """无有效 SKU 时生成飞书失败表一行说明（优先指向组合图/子编码）。"""
        merchant = str(merchant_code or "").strip().upper()
        if not merchant and listing_label:
            merchant = str(listing_label.split("/")[0] or "").strip().upper()

        for warning in cls._unit_warnings_for_label(preflight, listing_label):
            brief = cls._catalog_warning_to_brief(warning)
            if brief:
                return brief

        for source in (fallback_message, listing_label):
            brief = cls._catalog_warning_to_brief(str(source or ""))
            if brief:
                return brief

        if merchant:
            return cls.sanitize_feishu_failure_reason(f"{merchant}飞书无数据或名称未匹配")
        return cls.sanitize_feishu_failure_reason("飞书无商品数据或名称未匹配")

    @classmethod
    def build_preflight_no_skus_brief(
        cls,
        preflight: Any,
        listing_label: str,
        merchant_code: str = "",
    ) -> str:
        return cls.infer_no_sku_failure_brief(
            preflight=preflight,
            listing_label=listing_label,
            merchant_code=merchant_code,
        )

    @classmethod
    def build_preflight_no_skus_system_reason(
        cls,
        preflight: Any,
        listing_label: str,
        fallback_message: str = "",
    ) -> str:
        """无有效 SKU：从 preflight 单元 warnings / issues 拼飞书系统原因。"""
        label = str(listing_label or "").strip()
        fallback = cls.compact_system_diagnostic(fallback_message)
        if not label:
            return fallback

        units: list[Any] = []
        issues: list[Any] = []
        if isinstance(preflight, dict):
            units = list(preflight.get("units") or [])
            issues = list(preflight.get("issues") or [])
        elif preflight is not None:
            units = list(getattr(preflight, "units", None) or [])
            issues = list(getattr(preflight, "issues", None) or [])

        details: list[str] = []
        seen: set[str] = set()

        def _add(line: str) -> None:
            text = cls.compact_system_diagnostic(line)
            if not text or text in seen:
                return
            if text == label:
                return
            if text == "未解析到任何有效 SKU":
                return
            seen.add(text)
            details.append(text)

        for unit in units:
            unit_label = str(
                getattr(unit, "listing_label", None)
                or (unit.get("listing_label") if isinstance(unit, dict) else "")
                or ""
            ).strip()
            if unit_label != label:
                continue
            warnings = getattr(unit, "warnings", None) or (
                unit.get("warnings") if isinstance(unit, dict) else []
            ) or []
            for warning in warnings:
                _add(str(warning or ""))
            carousel = getattr(unit, "carousel_images", None) or (
                unit.get("carousel_images") if isinstance(unit, dict) else []
            ) or []
            detail_imgs = getattr(unit, "detail_images", None) or (
                unit.get("detail_images") if isinstance(unit, dict) else []
            ) or []
            material_img = getattr(unit, "material_image", None) or (
                unit.get("material_image") if isinstance(unit, dict) else None
            )
            material_note = "有" if material_img else "无"
            _add(f"主图 {len(carousel)} 张，详情图 {len(detail_imgs)} 张，商品素材 {material_note}")
            break

        for issue in issues:
            issue_label = str(
                getattr(issue, "listing_label", None)
                or (issue.get("listing_label") if isinstance(issue, dict) else "")
                or ""
            ).strip()
            if issue_label != label:
                continue
            level = str(
                getattr(issue, "level", None)
                or (issue.get("level") if isinstance(issue, dict) else "")
                or ""
            ).strip().lower()
            if level not in {"warning", "error"}:
                continue
            reason_code = str(
                getattr(issue, "reason_code", None)
                or (issue.get("reason_code") if isinstance(issue, dict) else "")
                or ""
            ).strip()
            if reason_code == ListingErrorCode.PREFLIGHT_NO_SKUS:
                continue
            _add(
                str(
                    getattr(issue, "message", None)
                    or (issue.get("message") if isinstance(issue, dict) else "")
                    or ""
                )
            )

        if details:
            brief = cls.infer_no_sku_failure_brief(
                preflight=preflight,
                listing_label=label,
                merchant_code=label.split("/")[0].strip() if label else "",
            )
            header = f"{brief}：" if brief else f"{label}："
            body = "；".join(details)
            return cls.sanitize_feishu_failure_reason(f"{header}{body}")[:2000]
        brief = cls.infer_no_sku_failure_brief(
            preflight=preflight,
            listing_label=label,
            merchant_code=label.split("/")[0].strip() if label else "",
            fallback_message=fallback,
        )
        if brief:
            return cls.sanitize_feishu_failure_reason(brief)[:2000]
        if fallback and fallback != label:
            return cls.sanitize_feishu_failure_reason(f"{label}：{fallback}")[:2000]
        return cls.sanitize_feishu_failure_reason(f"{label}：飞书无商品数据或名称未匹配")[:2000]

    @classmethod
    def _aspect_text_to_brief(cls, aspect_text: str) -> str:
        text = str(aspect_text or "").strip()
        return cls.FEISHU_BRIEF_ASPECT_TEXT.get(text, text.replace("数据缺失", "为空").replace("没数据", "为空"))

    @classmethod
    def feishu_catalog_line(
        cls,
        code: str,
        aspect: str,
        *,
        merchant_code: str = "",
        is_sub: bool = False,
    ) -> str:
        """飞书失败表一行：编码+具体问题（定价/控价/飞书无此行等）。"""
        code_text = str(code or "").strip().upper()
        merchant = str(merchant_code or "").strip().upper()

        if is_sub:
            if aspect in ("feishu_row_not_found", "product_row_missing", "subcode_missing"):
                if code_text:
                    return cls.sanitize_feishu_failure_reason(f"{code_text}飞书无此行")
                return "飞书无此行"
            suffix = cls.FEISHU_BRIEF_ASPECT.get(aspect, "数据缺失")
            line = f"{code_text}{suffix}" if code_text else suffix
            return cls.sanitize_feishu_failure_reason(line)

        if aspect in ("feishu_row_not_found", "product_row_missing", "subcode_missing"):
            line = f"{code_text}飞书无此行" if code_text else "飞书无此行"
            return cls.sanitize_feishu_failure_reason(line)
        suffix = cls.FEISHU_BRIEF_ASPECT.get(aspect, "数据缺失")
        line = f"{code_text}{suffix}" if code_text else suffix
        return cls.sanitize_feishu_failure_reason(line)

    @classmethod
    def format_numbered(cls, lines: list[str]) -> str:
        """多条失败合并：1、xxx，2、yyy；单条不加序号。"""
        cleaned: list[str] = []
        seen: set[str] = set()
        for line in lines:
            text = str(line or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0][:500]
        return "，".join(f"{idx}、{line}" for idx, line in enumerate(cleaned, 1))[:500]

    @staticmethod
    def _is_file_size_error_text(text: str) -> bool:
        compact = re.sub(r"\s+", "", str(text or ""))
        upper = compact.upper()
        if "大小不能超过" in compact:
            return True
        if "不能超过3MB" in upper or "不能超过3M" in upper:
            return True
        if "文件大小不能超过" in compact or "图片过大" in compact:
            return True
        return False

    @classmethod
    def compact_feishu_line(
        cls,
        raw: str,
        *,
        reason_code: str = "",
        merchant_code: str = "",
    ) -> str:
        """把旧格式/内部 message 压成飞书失败表一行短说明。"""
        text = str(raw or "").strip()
        if not text:
            code = str(merchant_code or "").strip().upper()
            rc = str(reason_code or "").strip()
            if rc == ListingErrorCode.PREFLIGHT_NO_CAROUSEL and code:
                return cls.Msg.FEISHU_CAROUSEL_MISSING.format(code=code)
            if rc == ListingErrorCode.PREFLIGHT_NO_DETAIL and code:
                return cls.Msg.FEISHU_DETAIL_MISSING.format(code=code)
            if rc == ListingErrorCode.PREFLIGHT_NO_MATERIAL and code:
                return cls.Msg.FEISHU_MATERIAL_MISSING.format(code=code)
            if rc == ListingErrorCode.PREFLIGHT_NO_SKUS:
                return cls.infer_no_sku_failure_brief(
                    merchant_code=code,
                )
            if code and rc.startswith("feishu_"):
                aspect = rc.replace("feishu_subcode_", "").replace("feishu_", "")
                aspect_key = aspect.replace("_missing", "_missing")
                mapping = {
                    "pricing_missing": "pricing_missing",
                    "control_missing": "control_missing",
                    "range_missing": "range_missing",
                    "range_min_missing": "range_min_missing",
                    "range_max_missing": "range_max_missing",
                    "color_spec_missing": "color_spec_missing",
                    "feishu_row_not_found": "feishu_row_not_found",
                    "product_row_missing": "feishu_row_not_found",
                    "subcode_missing": "subcode_missing",
                    "product_catalog_missing": "feishu_row_not_found",
                }
                is_sub = rc.startswith("feishu_subcode_")
                return cls.feishu_catalog_line(
                    code,
                    mapping.get(aspect, "feishu_row_not_found"),
                    merchant_code=merchant_code,
                    is_sub=is_sub,
                )
            return cls.feishu_label(rc) if rc else ""

        text = re.sub(r"^(失败|跳过)\s*[:：]\s*", "", text)

        catalog_brief = cls._catalog_warning_to_brief(text)
        if catalog_brief:
            return catalog_brief

        path_msg = re.match(r"^([A-Z0-9]+)/[^:：]+[:：]\s*(.+)", text, flags=re.I)
        if path_msg:
            if not merchant_code:
                merchant_code = path_msg.group(1).upper()
            text = path_msg.group(2).strip()

        for slot_prefix in (cls.Msg.SLOT_MISNAMED_PREFIX, cls.Msg.SLOT_PREFIX):
            if text.startswith(slot_prefix):
                inner = text[len(slot_prefix) :]
                inner = re.sub(r"[（(]应为\d+个[）)]", "", inner).strip()
                return inner

        sub = re.search(r"子编码\s+(\S+)\s+(.+)", text, flags=re.I)
        if sub:
            sub_code = str(sub.group(1) or "").strip().upper()
            aspect_brief = cls._aspect_text_to_brief(sub.group(2))
            if re.match(r"^[A-Z0-9]{3,}", sub_code):
                return f"{sub_code}{aspect_brief}"
            code_from_raw = re.search(r"(BD\d{3}[A-Z]?)", raw, flags=re.I)
            if code_from_raw:
                return f"{code_from_raw.group(1).upper()}{aspect_brief}"
            return aspect_brief

        fail = re.search(r"失败:\s*[^:]+:\s*(.+)", raw)
        if fail:
            aspect = fail.group(1).strip()
            code = str(merchant_code or "").strip().upper()
            if code and not re.match(r"^[A-Z0-9]+$", aspect[:6] if aspect else ""):
                return f"{code}{cls._aspect_text_to_brief(aspect)}"

        code_match = re.match(
            r"^(.+?)(拼多多定价|拼多多控价|PDD控价下限|PDD控价上限|定价|控价|控价区间|颜色规格|飞书无此行)(?:为空|没数据|数据缺失)?$",
            text,
            flags=re.I,
        )
        if code_match:
            code_part = str(code_match.group(1) or "").strip()
            aspect_word = str(code_match.group(2) or "").strip()
            aspect_map = {
                "拼多多定价": "pricing_missing",
                "定价": "pricing_missing",
                "拼多多控价": "control_missing",
                "控价": "control_missing",
                "PDD控价下限": "range_min_missing",
                "PDD控价上限": "range_max_missing",
                "控价区间": "range_missing",
                "颜色规格": "color_spec_missing",
                "飞书无此行": "feishu_row_not_found",
            }
            aspect_key = aspect_map.get(aspect_word, "")
            if aspect_key and code_part:
                return cls.feishu_catalog_line(code_part, aspect_key)

        vague_product = re.match(r"^(.+?)商品表(?:没数据|为空|数据缺失)$", text)
        if vague_product:
            code_part = str(vague_product.group(1) or "").strip()
            if code_part:
                return f"{code_part}飞书无此行"
            return "飞书无此行"

        legacy_code_match = re.match(r"^([A-Z0-9]{3,}[A-Z]?)(定价|控价|控价区间|颜色规格|商品表)", text, flags=re.I)
        if legacy_code_match:
            return text

        if "未找到 1-5 主图" in text or text == cls.Msg.CAROUSEL_EMPTY:
            code = str(merchant_code or "").strip().upper()
            return cls.Msg.FEISHU_CAROUSEL_MISSING.format(code=code) if code else "主图缺失"
        if "未找到 6-8 详情图" in text or "未找到 7-9 详情图" in text or text == cls.Msg.DETAIL_EMPTY:
            code = str(merchant_code or "").strip().upper()
            return cls.Msg.FEISHU_DETAIL_MISSING.format(code=code) if code else "详情图缺失"
        if "未找到 9 商品素材图" in text or text == cls.Msg.MATERIAL_EMPTY:
            code = str(merchant_code or "").strip().upper()
            return cls.Msg.FEISHU_MATERIAL_MISSING.format(code=code) if code else "商品素材图缺失"
        if cls._is_file_size_error_text(text):
            code = str(merchant_code or "").strip().upper()
            if "预览图" in text:
                brief = "预览图大小不能超过3MB"
            else:
                brief = "主图大小不能超过3MB"
            return f"{code}{brief}" if code else brief
        if "尺寸不符合" in text:
            code = str(merchant_code or "").strip().upper()
            if "预览图" in text:
                brief = "预览图尺寸不符合要求"
            else:
                brief = "主图尺寸不符合要求"
            return f"{code}{brief}" if code else brief
        if "数字命名图" in text:
            range_m = re.search(r"\((\d+)\s*-\s*(\d+)\)", text)
            if range_m:
                start_n, end_n = int(range_m.group(1)), int(range_m.group(2))
                if end_n >= start_n and end_n - start_n <= 12:
                    nums = " ".join(str(n) for n in range(start_n, end_n + 1))
                    return cls.Msg.FEISHU_IMAGES_MISSING.format(nums=nums)
            nums = re.findall(r"\d+", text)
            return cls.Msg.FEISHU_IMAGES_MISSING.format(nums=" ".join(nums)) if nums else "图片缺失"
        if "缺少预览图" in text:
            m = re.search(r"缺少预览图[:：]\s*(\S+)/(\S+)", text)
            if m:
                return f"{m.group(1)}缺预览图{m.group(2)}"
            return "缺预览图"

        rc = str(reason_code or "").strip()
        if rc in cls.VALIDATION_DETAIL_REASON_CODES and text:
            detail = cls.sanitize_feishu_failure_reason(text[:500])
            if detail and detail not in cls.FEISHU_LABELS.values():
                return detail

        if rc:
            brief = cls.compact_feishu_line("", reason_code=rc, merchant_code=merchant_code)
            if brief:
                return brief

        text = re.sub(r"^\[[^\]]+\]\s*", "", text)
        return cls.sanitize_feishu_failure_reason(text[:120])

    @classmethod
    def format_feishu_catalog_issue(
        cls,
        *,
        listing_label: str,
        code: str,
        aspect: str,
        is_sub: bool,
        merchant_code: str = "",
    ) -> tuple[str, str]:
        """生成飞书商品表缺项 (reason_code, message)。"""
        norm_code = str(code or "").strip().upper()
        parent_code = (
            str(merchant_code or "").strip().upper()
            or str(listing_label or "").split("/")[0].strip().upper()
        )
        reason_code, _ = cls.FEISHU_CATALOG_ASPECT.get(
            aspect,
            (ListingErrorCode.FEISHU_PRODUCT_CATALOG_MISSING, "飞书数据缺失"),
        )
        if is_sub:
            reason_code = cls.FEISHU_CATALOG_SUB_ASPECT.get(aspect, reason_code)
        message = cls.feishu_catalog_line(
            norm_code,
            aspect,
            merchant_code=parent_code,
            is_sub=is_sub,
        )
        return reason_code, message

    @classmethod
    def format_slot_mismatch(cls, detail: str, target: int) -> str:
        _ = target
        return cls.Msg.SLOT_MISMATCH.format(detail=detail, target=target)

    @classmethod
    def format_slot_mismatch_misnamed(cls, detail: str, target: int) -> str:
        _ = target
        return cls.Msg.SLOT_MISMATCH_MISNAMED_PREVIEW.format(detail=detail, target=target)

    @classmethod
    def format_slot_mismatch_feishu(cls, detail: str, target: int) -> str:
        _ = target
        return cls.Msg.FEISHU_SLOT_LINE.format(detail=detail)

    @classmethod
    def all_reason_codes(cls) -> list[str]:
        """列出所有已登记 reason_code（便于对照）。"""
        codes = {v for k, v in vars(ListingErrorCode).items() if not k.startswith("_")}
        codes.update(cls.LABELS)
        codes.update(cls.FEISHU_LABELS)
        return sorted(codes)
