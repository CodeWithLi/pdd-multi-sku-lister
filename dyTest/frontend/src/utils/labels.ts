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
  orchestrator: '智能规划',
}

export const listingStatusLabel: Record<string, string> = {
  success: '成功',
  step1_done: 'Step1 完成',
  step2_done: 'Step2 完成',
  step3_done: 'Step3 完成',
  step4_done: 'Step4 完成',
  step5_done: 'Step5 完成',
  failed: '失败',
  skipped: '已跳过',
  dry_run: '试运行',
}

export const issueLevelLabel: Record<string, string> = {
  error: '错误',
  warning: '警告',
}

export const loginModeLabel: Record<string, string> = {
  sms: '短信验证码',
  password: '账号密码',
}
