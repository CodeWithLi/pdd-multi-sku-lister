import type { AccountLifecycle, CommerceIntent } from '@/types'

const TRIGGER_LABELS: Record<string, string> = {
  manual: '手动',
  rabbitmq_auto: 'RabbitMQ',
  cycle_relist: '失败重跑',
  failure_sequential: '分阶段重跑',
}

const LIFECYCLE_STATUS_LABELS: Record<string, string> = {
  none: '空闲',
  active: '执行中',
  scheduled: '等活动',
  completed: '已完成',
  failed: '失败',
  canceled: '已取消',
}

const PHASE_LABELS: Record<string, string> = {
  listing: '上架',
  post_listing: '后置流程',
  scheduled: '预约等待',
  terminal: '已结束',
  active: '进行中',
}

const BLOCK_REASON_LABELS: Record<string, string> = {
  account_active: '店铺执行中',
  account_scheduled: '店铺等活动',
  product_claimed: '商品占用',
  duplicate_pending: '已在排队',
}

export function commerceTriggerLabel(source: string): string {
  return TRIGGER_LABELS[String(source || '').trim()] || source || '—'
}

export function commerceLifecycleStatusLabel(status: string): string {
  return LIFECYCLE_STATUS_LABELS[String(status || '').trim()] || status || '—'
}

export function commercePhaseLabel(phase: string): string {
  return PHASE_LABELS[String(phase || '').trim()] || phase || '—'
}

export function commerceBlockReasonLabel(reason: string): string {
  return BLOCK_REASON_LABELS[String(reason || '').trim()] || reason || '排队中'
}

export function commerceLifecycleTagType(
  status: string,
): 'success' | 'warning' | 'info' | 'danger' | '' {
  const key = String(status || '').trim()
  if (key === 'active') return 'warning'
  if (key === 'scheduled') return 'info'
  if (key === 'none') return 'success'
  if (key === 'failed' || key === 'canceled') return 'danger'
  return ''
}

export function formatWakeCountdown(wakeAt: string | null | undefined, nowMs = Date.now()): string {
  const raw = String(wakeAt || '').trim()
  if (!raw) return ''
  const target = new Date(raw).getTime()
  if (Number.isNaN(target)) return ''
  const diffMs = target - nowMs
  if (diffMs <= 0) return '即将继续'
  const totalMinutes = Math.ceil(diffMs / 60_000)
  if (totalMinutes < 60) return `约 ${totalMinutes} 分钟`
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours >= 24) {
    const days = Math.floor(hours / 24)
    const remHours = hours % 24
    return remHours > 0 ? `约 ${days} 天 ${remHours} 小时` : `约 ${days} 天`
  }
  return minutes > 0 ? `约 ${hours} 小时 ${minutes} 分` : `约 ${hours} 小时`
}

export function summarizeLifecycle(row: AccountLifecycle | null | undefined): string {
  if (!row || !row.lifecycle_status || row.lifecycle_status === 'none') {
    return '空闲，可立即启动'
  }
  const status = commerceLifecycleStatusLabel(row.lifecycle_status)
  const phase = commercePhaseLabel(row.phase)
  const countdown = row.lifecycle_status === 'scheduled' ? formatWakeCountdown(row.wake_at) : ''
  const parts = [status, phase]
  if (countdown) parts.push(countdown)
  return parts.filter(Boolean).join(' · ')
}

export function formatIntentProducts(selectors: string[], max = 2): string {
  const items = (selectors || []).filter(Boolean)
  if (!items.length) return '—'
  if (items.length <= max) return items.join('、')
  return `${items.slice(0, max).join('、')} 等 ${items.length} 个`
}

export function intentPriorityLabel(intent: CommerceIntent): string {
  const source = commerceTriggerLabel(intent.trigger_source)
  return `${source} · P${intent.priority}`
}
