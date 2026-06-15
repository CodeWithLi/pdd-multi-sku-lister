import type { RunRecord } from '@/types'

function isJsonLikeMessage(text: string): boolean {
  const t = text.trim()
  return t.startsWith('[{') || t.startsWith("{'") || t.startsWith('{"')
}

/** 从 run 记录提取简短错误说明，避免顶部展示整段 JSON。 */
export function summarizeRunError(run: Pick<RunRecord, 'message' | 'result'>): string {
  const result = (run.result || {}) as Record<string, unknown>
  const errors = result.errors
  if (Array.isArray(errors)) {
    for (const item of errors) {
      const text = String(item ?? '').trim()
      if (text && text !== 'marketing activity register failed') return text
    }
  }
  const results = result.results
  if (Array.isArray(results)) {
    for (const item of results) {
      if (!item || typeof item !== 'object') continue
      const row = item as Record<string, unknown>
      const msg = String(row.message || row.error || row.reason || '').trim()
      if (msg && String(row.status || '') !== 'success') {
        const step = String(row.step || '').trim()
        if (step === 'wait_price_confirm_page' || msg === 'price_confirm_page_not_ready') {
          return '未能进入价格确认页：浏览器停在活动大厅/详情页。已尝试关闭无关标签，请重试；若仍失败请手动保留价格确认页后再跑。'
        }
        if (step === 'expand_price_specs' || msg === 'expand_specs_incomplete') {
          return '未能展开全部规格：价格确认页仍有「展开更多规格」未点击，无法完整校验活动价。'
        }
        return step && !msg.includes(step) ? `${step}: ${msg}` : msg
      }
      const finalize = row.finalize_result
      if (finalize && typeof finalize === 'object') {
        const fin = finalize as Record<string, unknown>
        const finErr = String(fin.error || '').trim()
        if (finErr) return finErr
      }
    }
  }
  const msg = String(run.message || '').trim()
  if (!msg) return '任务失败'
  if (isJsonLikeMessage(msg)) return '任务失败，详见下方执行结果'
  return msg
}

/** 活动/任务结果里的步骤行（非 listing 商品行）。 */
export function extractCampaignStepRows(result?: Record<string, unknown>) {
  const results = result?.results
  if (!Array.isArray(results)) return []
  const rows: Record<string, unknown>[] = []

  for (const item of results) {
    if (!item || typeof item !== 'object') continue
    const payload = item as Record<string, unknown>
    const finalizeSteps = payload.finalize_result
    if (finalizeSteps && typeof finalizeSteps === 'object') {
      const steps = (finalizeSteps as Record<string, unknown>).steps
      if (Array.isArray(steps)) {
        for (const step of steps) {
          if (step && typeof step === 'object') {
            rows.push(step as Record<string, unknown>)
          }
        }
      }
    }
    if ('step' in payload || 'error' in payload) {
      rows.push(payload)
    }
  }
  return rows
}

export type ActivitySpecLookupRow = {
  spec_name: string
  activity_price: string
  pdd_product_id?: string
  product_code?: string
  spec_code?: string
  parent_code?: string
  child_code?: string
  match_score?: number
  match_method?: string
  floor_price?: number
  pricing?: number
  control_price?: number
  valid?: boolean
  should_remove?: boolean
  reason?: string
  reason_text?: string
  spec_name_source?: string
  spec_combined?: string
  spec_dim1_value?: string
  spec_dim2_value?: string
}

export type ActivityRemovedSpecRow = {
  spec_name: string
  spec_code: string
  activity_price: string | number
  floor_price?: number
  pricing?: number
  control_price?: number
  parent_code?: string
  child_code?: string
  reason: string
  reason_text: string
  deleted?: boolean
  delete_error?: string
  delete_error_text?: string
}

function firstResultPayload(result?: Record<string, unknown>): Record<string, unknown> | null {
  const results = result?.results
  if (!Array.isArray(results) || !results[0] || typeof results[0] !== 'object') return null
  return results[0] as Record<string, unknown>
}

function findPriceFilterBlock(payload: Record<string, unknown>): Record<string, unknown> | null {
  const direct = payload.price_filter
  if (direct && typeof direct === 'object') return direct as Record<string, unknown>
  const finalize = payload.finalize_result
  if (finalize && typeof finalize === 'object') {
    const nested = (finalize as Record<string, unknown>).price_filter
    if (nested && typeof nested === 'object') return nested as Record<string, unknown>
  }
  return null
}

function extractScrapeSpecs(payload: Record<string, unknown>): Record<string, unknown>[] {
  const blocks: Record<string, unknown>[] = []
  const specLookup = payload.spec_lookup
  if (specLookup && typeof specLookup === 'object') {
    blocks.push(specLookup as Record<string, unknown>)
  }
  const priceFilter = findPriceFilterBlock(payload)
  if (priceFilter) blocks.push(priceFilter)

  const specs: Record<string, unknown>[] = []
  for (const block of blocks) {
    const scrapeResult = block.scrape_result
    if (!scrapeResult || typeof scrapeResult !== 'object') continue
    const rows = (scrapeResult as Record<string, unknown>).specs
    if (!Array.isArray(rows)) continue
    for (const item of rows) {
      if (item && typeof item === 'object') specs.push(item as Record<string, unknown>)
    }
  }
  return specs
}

function scrapeMetaKey(row: Pick<ActivitySpecLookupRow, 'spec_name' | 'activity_price'>): string {
  return `${row.spec_name}||${row.activity_price}`
}

function mergeScrapeMeta(
  rows: ActivitySpecLookupRow[],
  scrapeSpecs: Record<string, unknown>[],
): ActivitySpecLookupRow[] {
  if (!scrapeSpecs.length) return rows
  const metaMap = new Map<string, Record<string, unknown>>()
  for (const item of scrapeSpecs) {
    metaMap.set(
      scrapeMetaKey({
        spec_name: String(item.spec_name || ''),
        activity_price: String(item.activity_price ?? ''),
      }),
      item,
    )
  }
  return rows.map((row) => {
    const scrape = metaMap.get(scrapeMetaKey(row))
    if (!scrape) return row
    return {
      ...row,
      spec_name_source: String(scrape.spec_name_source || row.spec_name_source || ''),
      spec_combined: String(scrape.spec_combined || row.spec_combined || ''),
      spec_dim1_value: String(scrape.spec_dim1_value || row.spec_dim1_value || ''),
      spec_dim2_value: String(scrape.spec_dim2_value || row.spec_dim2_value || ''),
    }
  })
}

function mapValidationRow(row: Record<string, unknown>): ActivitySpecLookupRow {
  return {
    spec_name: String(row.spec_name || ''),
    activity_price: String(row.activity_price ?? ''),
    pdd_product_id: String(row.pdd_product_id || ''),
    product_code: String(row.product_code || ''),
    spec_code: String(row.spec_code || row.combo_folder || ''),
    parent_code: String(row.parent_code || ''),
    child_code: String(row.child_code || ''),
    match_score: row.sku_matched ? 100 : 0,
    match_method: String(row.match_method || ''),
    floor_price: row.floor_price as number | undefined,
    pricing: row.pricing as number | undefined,
    control_price: row.control_price as number | undefined,
    valid: row.valid as boolean | undefined,
    should_remove: row.should_remove as boolean | undefined,
    reason: String(row.reason || ''),
    reason_text: String(row.reason_text || ''),
    spec_name_source: String(row.spec_name_source || ''),
    spec_combined: String(row.spec_combined || ''),
    spec_dim1_value: String(row.spec_dim1_value || ''),
    spec_dim2_value: String(row.spec_dim2_value || ''),
  }
}

function mapRemovedSpecRow(row: Record<string, unknown>): ActivityRemovedSpecRow {
  return {
    spec_name: String(row.spec_name || ''),
    spec_code: String(row.spec_code || ''),
    activity_price: row.activity_price as string | number,
    floor_price: row.floor_price as number | undefined,
    pricing: row.pricing as number | undefined,
    control_price: row.control_price as number | undefined,
    parent_code: String(row.parent_code || ''),
    child_code: String(row.child_code || ''),
    reason: String(row.reason || ''),
    reason_text: String(row.reason_text || row.reason || ''),
    deleted: row.deleted as boolean | undefined,
    delete_error: String(row.delete_error || ''),
    delete_error_text: String(row.delete_error_text || ''),
  }
}

function mapScrapeOnlyRow(row: Record<string, unknown>): ActivitySpecLookupRow {
  return {
    spec_name: String(row.spec_name || ''),
    activity_price: String(row.activity_price ?? ''),
    spec_name_source: String(row.spec_name_source || ''),
    spec_combined: String(row.spec_combined || ''),
    spec_dim1_value: String(row.spec_dim1_value || ''),
    spec_dim2_value: String(row.spec_dim2_value || ''),
  }
}

/** 活动规格反查/价格校验汇总（匹配数等）。 */
export function extractActivitySpecLookupMeta(result?: Record<string, unknown>) {
  const payload = firstResultPayload(result)
  if (!payload) return null

  const specLookup = payload.spec_lookup
  if (specLookup && typeof specLookup === 'object') {
    return specLookup as Record<string, unknown>
  }

  const rows = extractActivitySpecLookupRows(result)
  if (!rows.length) return null
  return {
    spec_count: rows.length,
    matched_count: rows.filter((row) => row.spec_code).length,
    rows,
  }
}

/** 从 campaign 任务结果提取规格反查/价格校验行（21365 spec_lookup / 20981 validation）。 */
export function extractActivitySpecLookupRows(result?: Record<string, unknown>): ActivitySpecLookupRow[] {
  const payload = firstResultPayload(result)
  if (!payload) return []

  const specLookup = payload.spec_lookup
  if (specLookup && typeof specLookup === 'object') {
    const rows = (specLookup as Record<string, unknown>).rows
    if (Array.isArray(rows) && rows.length) {
      return mergeScrapeMeta(rows as ActivitySpecLookupRow[], extractScrapeSpecs(payload))
    }
  }

  let items: unknown[] | undefined
  const topValidation = payload.validation
  if (topValidation && typeof topValidation === 'object') {
    items = (topValidation as Record<string, unknown>).results as unknown[] | undefined
  }
  if (!items?.length) {
    const priceFilter = findPriceFilterBlock(payload)
    if (priceFilter) {
      const pfValidation = priceFilter.validation
      if (pfValidation && typeof pfValidation === 'object') {
        items = (pfValidation as Record<string, unknown>).results as unknown[] | undefined
      }
      if (!items?.length && Array.isArray(priceFilter.results)) {
        items = priceFilter.results
      }
    }
  }

  if (Array.isArray(items) && items.length) {
    return mergeScrapeMeta(
      items
        .filter((item) => item && typeof item === 'object')
        .map((item) => mapValidationRow(item as Record<string, unknown>)),
      extractScrapeSpecs(payload),
    )
  }

  const scrapeSpecs = extractScrapeSpecs(payload)
  if (!scrapeSpecs.length) return []
  return scrapeSpecs.map((item) => mapScrapeOnlyRow(item))
}

/** 提取被删除/不符合价格条件的规格明细（含原因说明）。 */
export function extractActivityRemovedSpecRows(result?: Record<string, unknown>): ActivityRemovedSpecRow[] {
  const payload = firstResultPayload(result)
  if (!payload) return []

  const blocks: Record<string, unknown>[] = []
  const priceFilter = findPriceFilterBlock(payload)
  if (priceFilter) blocks.push(priceFilter)
  const finalize = payload.finalize_result
  if (finalize && typeof finalize === 'object') blocks.push(finalize as Record<string, unknown>)

  for (const block of blocks) {
    const removed = block.removed_specs
    if (Array.isArray(removed) && removed.length) {
      return removed
        .filter((item) => item && typeof item === 'object')
        .map((item) => mapRemovedSpecRow(item as Record<string, unknown>))
    }
    const filterResult = block.filter_result
    if (filterResult && typeof filterResult === 'object') {
      const nested = (filterResult as Record<string, unknown>).removed_specs
      if (Array.isArray(nested) && nested.length) {
        return nested
          .filter((item) => item && typeof item === 'object')
          .map((item) => mapRemovedSpecRow(item as Record<string, unknown>))
      }
    }
    const validation = block.validation
    if (validation && typeof validation === 'object') {
      const nested = (validation as Record<string, unknown>).removed_specs
      if (Array.isArray(nested) && nested.length) {
        return nested
          .filter((item) => item && typeof item === 'object')
          .map((item) => mapRemovedSpecRow(item as Record<string, unknown>))
      }
    }
  }

  return extractActivitySpecLookupRows(result)
    .filter((row) => row.should_remove)
    .map((row) =>
      mapRemovedSpecRow({
        spec_name: row.spec_name,
        spec_code: row.spec_code,
        activity_price: row.activity_price,
        floor_price: row.floor_price,
        pricing: row.pricing,
        control_price: row.control_price,
        parent_code: row.parent_code,
        child_code: row.child_code,
        reason: row.reason,
        reason_text: row.reason_text,
      }),
    )
}

export type ActivityRegistrationProductOutcome =
  | 'submitted'
  | 'removed'
  | 'blocked'
  | 'not_submitted'
  | 'prepared_only'
  | 'unknown'

export type ActivityRegistrationProductRow = {
  pdd_product_id: string
  product_code: string
  outcome: ActivityRegistrationProductOutcome
  outcome_label: string
  passed_specs: number
  failed_specs: number
  total_specs: number
  detail: string
}

export type ActivityRegistrationSummary = {
  visible: boolean
  headline: string
  headline_type: 'success' | 'warning' | 'danger' | 'info'
  submitted: boolean | null
  selected_count: number
  submitted_count: number
  removed_count: number
  blocked_count: number
  spec_passed: number
  spec_failed: number
  spec_total: number
  products: ActivityRegistrationProductRow[]
  notes: string[]
}

function isCampaignRegistrationPayload(payload: Record<string, unknown>): boolean {
  if (Array.isArray(payload.product_ids) && payload.product_ids.length) return true
  if (payload.activity_id) return true
  if (payload.finalize_result) return true
  if (payload.spec_lookup) return true
  const step = String(payload.step || '')
  return ['register_completed', 'price_page_prepared', 'product_pick_confirmed', 'register_submitted'].includes(step)
}

function detectActivitySubmitted(payload: Record<string, unknown>): boolean | null {
  const step = String(payload.step || '')
  if (step === 'price_page_prepared' || step === 'product_pick_confirmed') return null

  if (String(payload.status || '') === 'cancelled') return false

  const priceFilter = payload.price_filter
  if (priceFilter && typeof priceFilter === 'object') {
    const pf = priceFilter as Record<string, unknown>
    if (pf.action === 'partial_invalid_needs_manual') return false
  }

  const finalize = payload.finalize_result
  if (finalize && typeof finalize === 'object') {
    const fin = finalize as Record<string, unknown>
    if (fin.status === 'cancelled' || fin.status === 'failed') return false
    const priceFilter = fin.price_filter
    if (priceFilter && typeof priceFilter === 'object') {
      const pf = priceFilter as Record<string, unknown>
      if (pf.status === 'all_products_removed') return false
      if (pf.action === 'close_page') return false
    }
    const submit = fin.confirm_submit
    if (submit && typeof submit === 'object') {
      if ((submit as Record<string, unknown>).clicked === true) {
        const verify = fin.submit_verification
        if (verify && typeof verify === 'object') {
          if ((verify as Record<string, unknown>).verified === false) return false
          if ((verify as Record<string, unknown>).verified === true) return true
        }
        return true
      }
      if ((submit as Record<string, unknown>).clicked === false) return false
    }
    if (fin.status === 'success' && step === 'register_completed') return true
  }

  const confirm = payload.confirm_result
  if (confirm && typeof confirm === 'object') {
    const clicked = (confirm as Record<string, unknown>).clicked
    if (clicked === true) return true
  }

  if (step === 'register_completed' && String(payload.status || '') === 'success') return true
  return null
}

function groupSpecRowsByProduct(rows: ActivitySpecLookupRow[]): Map<string, ActivitySpecLookupRow[]> {
  const grouped = new Map<string, ActivitySpecLookupRow[]>()
  for (const row of rows) {
    const pid = String(row.pdd_product_id || row.product_code || 'unknown').trim() || 'unknown'
    const bucket = grouped.get(pid) || []
    bucket.push(row)
    grouped.set(pid, bucket)
  }
  return grouped
}

function countSpecStates(rows: ActivitySpecLookupRow[]) {
  const passed = rows.filter((row) => row.valid === true && !row.should_remove).length
  const failed = rows.filter((row) => row.should_remove || row.valid === false).length
  return { passed, failed, total: rows.length }
}

function resolveProductOutcome(
  pid: string,
  specs: ActivitySpecLookupRow[],
  ctx: {
    submitted: boolean | null
    step: string
    partialIds: Set<string>
    removedIds: Set<string>
    skippedDelete: boolean
    removedSpecCodes: Set<string>
  },
): ActivityRegistrationProductRow {
  const productCode = String(specs[0]?.product_code || pid || '').trim()
  const { passed, failed, total } = countSpecStates(specs)
  const base = {
    pdd_product_id: pid,
    product_code: productCode,
    passed_specs: passed,
    failed_specs: failed,
    total_specs: total,
  }

  if (ctx.step === 'price_page_prepared') {
    return {
      ...base,
      outcome: 'prepared_only',
      outcome_label: '仅反查',
      detail: '已完成价格确认页准备，未点击正式提交报名',
    }
  }

  if (ctx.submitted === false) {
    if (ctx.partialIds.has(pid) || ctx.removedIds.has(pid) || (failed > 0 && passed === 0)) {
      const detail = ctx.partialIds.has(pid) && failed > 0
        ? `${failed} 条规格不合格（共 ${total} 条），有一不合格即整商品剔除，未参与报名`
        : ctx.removedIds.has(pid)
          ? '全部规格不合格或已整商品剔除，未参与报名'
          : '商品不符合条件，已从价格确认页剔除'
      return {
        ...base,
        outcome: 'removed',
        outcome_label: '已剔除',
        detail,
      }
    }
    return {
      ...base,
      outcome: 'not_submitted',
      outcome_label: '未报名',
      detail: '任务未提交到拼多多（可能全部商品被剔除或流程中断）',
    }
  }

  if (ctx.removedIds.has(pid) || ctx.partialIds.has(pid)) {
    if (ctx.partialIds.has(pid) && failed > 0) {
      return {
        ...base,
        outcome: 'removed',
        outcome_label: '已剔除',
        detail:
          passed > 0
            ? `${failed} 条规格不合格（共 ${total} 条），有一不合格即整商品剔除，未参与报名`
            : '全部规格不合格，整商品已删除',
      }
    }
  }

  if (ctx.removedIds.has(pid) || (passed === 0 && failed > 0)) {
    const removedBySpec = specs.some((row) => row.spec_code && ctx.removedSpecCodes.has(row.spec_code))
    if (removedBySpec || ctx.removedIds.has(pid)) {
      return {
        ...base,
        outcome: 'removed',
        outcome_label: '未报名',
        detail: '全部规格不合格或已删除，未参与最终提交',
      }
    }
  }

  if (ctx.submitted === true) {
    if (passed > 0) {
      return {
        ...base,
        outcome: 'submitted',
        outcome_label: '已提交报名',
        detail:
          failed > 0
            ? `共 ${total} 条规格，${passed} 条合格并已提交`
            : `共 ${passed} 条规格全部合格并已提交`,
      }
    }
    return {
      ...base,
      outcome: 'removed',
      outcome_label: '未报名',
      detail: '无合格规格参与提交',
    }
  }

  return {
    ...base,
    outcome: 'unknown',
    outcome_label: '待确认',
    detail: '请查看下方规格明细或在拼多多后台核对报名结果',
  }
}

/** 活动报名最终结果摘要：一眼看出有没有商品提交成功。 */
export function extractActivityRegistrationSummary(
  result?: Record<string, unknown>,
): ActivityRegistrationSummary | null {
  const payload = firstResultPayload(result)
  if (!payload || !isCampaignRegistrationPayload(payload)) return null

  const step = String(payload.step || '')
  const submitted = detectActivitySubmitted(payload)
  const specRows = extractActivitySpecLookupRows(result)
  const removedRows = extractActivityRemovedSpecRows(result)
  const priceFilter = findPriceFilterBlock(payload)
  const filterResult =
    priceFilter?.filter_result && typeof priceFilter.filter_result === 'object'
      ? (priceFilter.filter_result as Record<string, unknown>)
      : null

  const partialIds = new Set(
    (Array.isArray(filterResult?.partial_product_ids)
      ? filterResult?.partial_product_ids
      : []
    ).map((item) => String(item || '').trim()).filter(Boolean),
  )
  const removedIds = new Set(
    (Array.isArray(filterResult?.removed_product_ids)
      ? filterResult?.removed_product_ids
      : []
    ).map((item) => String(item || '').trim()).filter(Boolean),
  )
  const skippedDelete = priceFilter?.action === 'partial_invalid_needs_manual'
  const filterSummary =
    typeof priceFilter?.filter_summary === 'string' ? String(priceFilter.filter_summary).trim() : ''

  const removedSpecCodes = new Set(
    removedRows
      .filter((row) => row.deleted !== false)
      .map((row) => String(row.spec_code || '').trim())
      .filter(Boolean),
  )

  const selectedIds = Array.isArray(payload.product_ids)
    ? payload.product_ids.map((item) => String(item || '').trim()).filter(Boolean)
    : []

  const grouped = groupSpecRowsByProduct(specRows)
  const productKeys = selectedIds.length
    ? selectedIds
    : Array.from(grouped.keys()).filter((key) => key !== 'unknown')

  const products = productKeys.map((pid) => {
    const specs = grouped.get(pid) || []
    return resolveProductOutcome(pid, specs, {
      submitted,
      step,
      partialIds,
      removedIds,
      skippedDelete,
      removedSpecCodes,
    })
  })

  const submittedCount = products.filter((row) => row.outcome === 'submitted').length
  const blockedCount = products.filter((row) => row.outcome === 'blocked').length
  const removedCount = products.filter((row) => row.outcome === 'removed' || row.outcome === 'not_submitted').length
  const specPassed = specRows.filter((row) => row.valid === true && !row.should_remove).length
  const specFailed = specRows.filter((row) => row.should_remove || row.valid === false).length
  const selectedCount = productKeys.length || selectedIds.length

  let headline = '报名结果待确认'
  let headline_type: ActivityRegistrationSummary['headline_type'] = 'info'
  const notes: string[] = []

  if (submitted === true) {
    if (submittedCount <= 0) {
      headline = '未有任何商品完成报名'
      headline_type = 'danger'
      notes.push('任务虽执行完成，但没有商品带着合格规格提交到拼多多。')
    } else if (blockedCount > 0 || removedCount > 0) {
      headline = `报名已提交：${submittedCount}/${selectedCount || submittedCount} 个商品`
      headline_type = 'warning'
      if (blockedCount > 0) {
        notes.push(`${blockedCount} 个商品含未能自动剔除的不合格规格，请到拼多多后台核对。`)
      }
      if (removedCount > 0) {
        notes.push(`${removedCount} 个商品未参与报名（已剔除或无合格规格）。`)
      }
    } else {
      headline = `报名成功：${submittedCount} 个商品已提交`
      headline_type = 'success'
    }
  } else if (submitted === false) {
    if (filterSummary) {
      headline = '未提交报名'
      headline_type = 'danger'
      notes.push(filterSummary.split('\n')[0])
    } else {
      headline = '未提交报名'
      headline_type = 'danger'
      notes.push('全部商品被剔除或任务在提交前已终止。')
    }
  } else if (step === 'price_page_prepared') {
    headline = '仅完成规格反查，未正式提交报名'
    headline_type = 'warning'
    notes.push('本活动此前配置为只反查不提交；若需自动点「确认提交」，请更新后端后重试。')
  } else if (step === 'register_completed' && String(payload.status || '') === 'success') {
    headline = submittedCount > 0 ? `报名已提交：${submittedCount} 个商品` : '报名结果待后台核对'
    headline_type = submittedCount > 0 ? 'success' : 'warning'
  }

  if (specRows.length) {
    notes.push(`规格价格：${specPassed} 条合格 / ${specFailed} 条不合格（共 ${specRows.length} 条）。`)
  }
  if (filterSummary) {
    for (const line of filterSummary.split('\n').filter(Boolean)) {
      if (!notes.includes(line)) notes.push(line)
    }
  }
  if (removedRows.some((row) => row.deleted === false)) {
    notes.push('部分不合格商品未能从活动页删除，请手动处理后重试。')
  }

  return {
    visible: true,
    headline,
    headline_type,
    submitted,
    selected_count: selectedCount,
    submitted_count: submittedCount,
    removed_count: removedCount,
    blocked_count: blockedCount,
    spec_passed: specPassed,
    spec_failed: specFailed,
    spec_total: specRows.length,
    products,
    notes,
  }
}

export function formatActivityRegistrationMessage(summary: ActivityRegistrationSummary | null): string {
  if (!summary?.visible) return ''
  const parts = [summary.headline]
  if (summary.notes.length) parts.push(summary.notes[0])
  return parts.join('；')
}
