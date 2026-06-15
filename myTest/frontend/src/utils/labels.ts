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
