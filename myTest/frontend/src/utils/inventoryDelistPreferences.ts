import type { InventoryDelistExecutionMode } from '@/types/inventoryDelist'

const STORAGE_KEY = 'pdd_agent.inventory_delist.preferences'

export interface InventoryDelistPreferences {
  enabled: boolean
  interval_hours: number
  account_ids: string[]
  execution_mode: InventoryDelistExecutionMode
  delist_spec_code_search_enabled: boolean
  test_override_enabled?: boolean
  test_override_selected?: string[]
  test_override_default_qty?: number
  test_delist_dry_run?: boolean
}

export interface AccountAliasSource {
  account_id: string
  username?: string
  shop_display_name?: string
  display_name?: string
}

const DEFAULTS: InventoryDelistPreferences = {
  enabled: false,
  interval_hours: 6,
  account_ids: [],
  execution_mode: 'parallel',
  delist_spec_code_search_enabled: false,
  test_override_enabled: false,
  test_override_selected: [],
  test_override_default_qty: -1,
  test_delist_dry_run: true,
}

function normalize(payload: Partial<InventoryDelistPreferences>): InventoryDelistPreferences {
  const mode = payload.execution_mode === 'sequential' ? 'sequential' : 'parallel'
  let interval = Number(payload.interval_hours)
  if (!Number.isFinite(interval)) interval = DEFAULTS.interval_hours
  interval = Math.max(0.5, Math.min(168, interval))
  const account_ids = Array.isArray(payload.account_ids)
    ? payload.account_ids.map((id) => String(id).trim()).filter(Boolean)
    : []
  return {
    enabled: Boolean(payload.enabled),
    interval_hours: interval,
    account_ids: [...new Set(account_ids)],
    execution_mode: mode,
    delist_spec_code_search_enabled: Boolean(payload.delist_spec_code_search_enabled),
    test_override_enabled: Boolean(payload.test_override_enabled),
    test_override_selected: Array.isArray(payload.test_override_selected)
      ? payload.test_override_selected.map((c) => String(c).trim()).filter(Boolean)
      : [],
    test_override_default_qty: Number.isFinite(Number(payload.test_override_default_qty))
      ? Number(payload.test_override_default_qty)
      : -1,
    test_delist_dry_run: payload.test_delist_dry_run !== false,
  }
}

export function loadInventoryDelistPreferences(): InventoryDelistPreferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULTS }
    return normalize(JSON.parse(raw) as Partial<InventoryDelistPreferences>)
  } catch {
    return { ...DEFAULTS }
  }
}

export function saveInventoryDelistPreferences(prefs: Partial<InventoryDelistPreferences>): void {
  try {
    const merged = normalize({ ...loadInventoryDelistPreferences(), ...prefs })
    localStorage.setItem(STORAGE_KEY, JSON.stringify(merged))
  } catch {
    // ignore quota / private mode
  }
}

/** 将 account_id / 登录名 / 店铺展示名 统一解析为规范 account_id。 */
export function resolveAccountIds(
  accountIds: string[],
  accounts: AccountAliasSource[],
): string[] {
  const validIds = new Set(
    accounts.map((acc) => String(acc.account_id || '').trim()).filter(Boolean),
  )
  const aliasToId = new Map<string, string>()
  for (const acc of accounts) {
    const id = String(acc.account_id || '').trim()
    if (!id) continue
    for (const alias of [id, acc.username, acc.shop_display_name, acc.display_name]) {
      const key = String(alias || '').trim()
      if (key && !aliasToId.has(key)) aliasToId.set(key, id)
    }
  }
  const resolved: string[] = []
  const seen = new Set<string>()
  for (const raw of accountIds) {
    const key = String(raw).trim()
    if (!key) continue
    const id = aliasToId.get(key) ?? (validIds.has(key) ? key : '')
    if (id && !seen.has(id)) {
      seen.add(id)
      resolved.push(id)
    }
  }
  return resolved
}

export function filterValidAccountIds(
  accountIds: string[],
  availableIds: string[],
): string[] {
  const allowed = new Set(availableIds.map((id) => String(id).trim()).filter(Boolean))
  return accountIds.filter((id) => allowed.has(id))
}

export function mergeInventoryDelistPreferences(
  server: Partial<InventoryDelistPreferences>,
  local: Partial<InventoryDelistPreferences>,
  accounts: AccountAliasSource[],
): InventoryDelistPreferences {
  const localNorm = normalize(local)
  const serverNorm = normalize(server)
  const rawIds = localNorm.account_ids.length ? localNorm.account_ids : serverNorm.account_ids
  const account_ids = resolveAccountIds(rawIds, accounts)
  return normalize({
    ...serverNorm,
    ...localNorm,
    account_ids,
    test_override_enabled: localNorm.test_override_enabled ?? serverNorm.test_override_enabled,
    test_override_selected: localNorm.test_override_selected?.length
      ? localNorm.test_override_selected
      : serverNorm.test_override_selected,
    test_override_default_qty:
      localNorm.test_override_default_qty ?? serverNorm.test_override_default_qty,
    test_delist_dry_run: localNorm.test_delist_dry_run ?? serverNorm.test_delist_dry_run,
  })
}
