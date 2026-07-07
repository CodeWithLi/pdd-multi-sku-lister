export const runStatusLabel: Record<string, string> = {
  success: '成功',
  failed: '失败',
  canceled: '已取消',
  running: '进行中',
  pending: '等待中',
  queued: '排队中',
  needs_human: '需人工处理',
  skipped: '已跳过',
}

export const runStatusType: Record<string, string> = {
  success: 'success',
  failed: 'danger',
  canceled: 'info',
  running: 'warning',
  pending: 'info',
  needs_human: 'warning',
  skipped: 'info',
}

export const agentLabel: Record<string, string> = {
  listing: '商品上架',
  delist: '商品下架',
  campaign: '活动',
  traffic: '推广',
  orchestrator: '智能规划',
}

export const listingStatusLabel: Record<string, string> = {
  success: '成功',
  retryable: '可重试',
  listed: '上架成功',
  failed: '失败',
  skipped: '已跳过',
  submit_uncertain: '待确认',
  delist: '已下架',
  dry_run: '试运行命中',
  delisted: '已下架',
}

export const listingStatusType: Record<string, string> = {
  success: 'success',
  listed: 'success',
  retryable: 'warning',
  submit_uncertain: 'warning',
  failed: 'danger',
  skipped: 'info',
  dry_run: 'info',
  delist: 'success',
  delisted: 'success',
}

export const issueLevelLabel: Record<string, string> = {
  error: '错误',
  warning: '警告',
}

/** 上架失败 reason_code → 人工可读说明（与后端 ListingErrors.LABELS 对齐，改文案请同步 domain/listing_errors.py） */
export const failureReasonLabel: Record<string, string> = {
  preview_not_ready: '预览图未全部上传',
  preview_missing: '预览图缺失或未通过校验',
  platform_listing_code_not_filled: '底部商品编码未填写',
  platform_listing_code_verify_failed: '底部商品编码与货号不一致',
  validation_errors: '提交前校验失败（库存/价格等未填完整）',
  validation_incomplete: '提交前信息不完整',
  validation_required: '提交前有必填项未处理',
  submit_blocked: '提交被页面拦截',
  submit_uncertain: '提交结果不确定',
  submit_button_missing: '未找到提交按钮',
  submit_exception: '点击提交异常',
  rejected_after_publish: '提交后被平台驳回',
  published_but_not_found_in_on_sale_or_rejected: '提交后未在售/驳回列表找到',
  needs_manual_login_or_captcha: '需人工登录或验证码',
  page_or_material_changed: '页面结构或素材异常',
  browser_transient_error: '浏览器超时或断开',
  unexpected_error: '未分类异常',
  preflight_no_skus: '上架前校验：无有效 SKU',
  preflight_no_carousel: '上架前校验：主图为空',
  preflight_no_detail: '上架前校验：详情图为空',
  preflight_no_material: '上架前校验：商品素材图为空',
  preflight_catalog: '上架前校验：商品表或目录问题',
  image_file_missing: '图片文件不存在或无法打开',
  price_fill_partial: '价格表未全部填写',
  price_fill_row_not_found: '价格表找不到规格行',
  price_fill_by_index_failed: '按行号填价格表失败',
  no_valid_units: '无有效上架单元',
  feishu_product_catalog_missing: '飞书商品/定价数据缺失',
  feishu_pricing_missing: '定价数据缺失',
  feishu_control_missing: '控价数据缺失',
  feishu_price_range_missing: '零售综合成本没数据',
  feishu_color_spec_missing: '颜色规格没数据',
  feishu_row_not_found: '飞书无此行',
  feishu_product_row_missing: '飞书无此行',
  feishu_subcode_missing: '飞书无子编码',
  feishu_subcode_pricing_missing: '子编码定价数据缺失',
  feishu_subcode_control_missing: '子编码控价数据缺失',
  feishu_subcode_range_missing: '子编码零售综合成本没数据',
  feishu_subcode_color_spec_missing: '子编码颜色规格没数据',
  skipped_already_listed: '商品已上架，已跳过',
  listing_failed: '上架失败',
  slot_alignment_failed: '兄弟款规格数量不一致',
  spec_fill_verify_failed: '规格校验填表未通过',
  negative_inventory_skip: '可用库存小于0，跳过上架',
}

export const listingUnitStatusType: Record<string, string> = {
  skipped: 'info',
  preflight_failed: 'danger',
  ready: 'success',
  pending: 'info',
  listing: 'warning',
  success: 'success',
  failed: 'danger',
  canceled: 'info',
}
