import type { WecomDailyReportPlatform } from '@/types'

function splitLines(text: string): string[] {
  return String(text || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

function bulletBlock(text: string, emptyLabel = '暂无'): string {
  const lines = splitLines(text)
  if (!lines.length) {
    return `> <font color="comment">${emptyLabel}</font>`
  }
  return lines.map((line) => `- ${line}`).join('\n')
}

function platformTitle(platform: WecomDailyReportPlatform): string {
  return platform === 'pdd' ? 'PDD' : '淘宝'
}

export function formatListingWindow(start: string, end: string): string {
  const s = String(start || '').trim()
  const e = String(end || '').trim()
  if (!s || !e) return ''
  const short = (value: string) => (value.length > 5 ? value.slice(5) : value)
  return `${short(s)} ~ ${short(e)}`
}

export interface DailyReportMarkdownInput {
  platform: WecomDailyReportPlatform
  reportDate: string
  progressSummary?: string
  storeProgress?: string
  netdiskMaterials?: string
  inProgress?: string
  listingWindowStart?: string
  listingWindowEnd?: string
}

export function buildDailyReportMarkdown(input: DailyReportMarkdownInput): string {
  const label = platformTitle(input.platform)
  const parts = [
    `## 日报 · ${label}`,
    `> 日期：<font color="info">${input.reportDate}</font>`,
    '',
  ]

  if (input.platform === 'pdd') {
    parts.push(
      '### 当日已完成交付技术项目进展',
      bulletBlock(input.progressSummary || '', '今日暂无代码提交'),
      '',
      '### 店铺今日发布商品进度',
    )
    const listingWindow = formatListingWindow(
      input.listingWindowStart || '',
      input.listingWindowEnd || '',
    )
    if (listingWindow) {
      parts.push(`> 统计窗口：<font color="comment">${listingWindow}</font>`)
    }
    parts.push(
      bulletBlock(input.storeProgress || '', '暂无发布记录'),
      '',
      '### 正在解决 / 优化中',
      bulletBlock(input.inProgress || '', '暂无'),
    )
    return parts.join('\n')
  }

  parts.push(
    '### 网盘素材和上架累计数据',
    bulletBlock(input.netdiskMaterials || '', '暂无'),
    '',
    '### 正在解决 / 优化中',
    bulletBlock(input.inProgress || '', '暂无'),
  )
  return parts.join('\n')
}
