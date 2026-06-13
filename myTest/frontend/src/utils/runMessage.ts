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
      if (text) return text
    }
  }
  const results = result.results
  if (Array.isArray(results)) {
    for (const item of results) {
      if (!item || typeof item !== 'object') continue
      const row = item as Record<string, unknown>
      if (String(row.status || '') === 'success') continue
      const err = String(row.error || '').trim()
      if (err) {
        const step = String(row.step || '').trim()
        return step ? `${step}: ${err}` : err
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
