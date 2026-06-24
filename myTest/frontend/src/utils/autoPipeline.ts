export interface AutoPipelineResult {
  triggered?: boolean
  reason?: string
  reason_label?: string
  product_codes?: string[]
  group_change_types?: string[]
}

const REASON_LABELS: Record<string, string> = {
  disabled: '自动上架未开启',
  missing_account_id: '未配置店铺，请在「自动化配置」中选择店铺并保存',
  missing_activity_ids: '未配置营销活动',
  no_matching_groups:
    '上传类型与触发范围不匹配（当前为追加图片，需选「仅追加文件」或「都可以」）',
  dedup: '近期已触发过相同商品（120 秒内去重）',
  append_only_batch: '本批次为追加图片或重复通知，已跳过自动上架',
  no_indexed_files: '没有成功索引的图片',
  batch_not_success: '上传批次未成功，未触发自动上架',
}

export function autoPipelineReasonLabel(result: AutoPipelineResult | undefined | null): string {
  if (!result) return ''
  if (result.reason_label) return result.reason_label
  if (result.reason) return REASON_LABELS[result.reason] || result.reason
  return ''
}

export function formatAutoPipelineFeedback(result: AutoPipelineResult | undefined | null): string {
  if (!result) return ''
  if (result.triggered) {
    const codes = result.product_codes?.length ? result.product_codes.join('、') : '新商品'
    return `已自动启动整合链路：${codes}`
  }
  const label = autoPipelineReasonLabel(result)
  if (!label) return ''
  const types = result.group_change_types?.length
    ? `（本次识别为：${result.group_change_types.join('、')}）`
    : ''
  return `自动上架未触发：${label}${types}`
}
