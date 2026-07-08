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
  availableAccountIds: string[],
): InventoryDelistPreferences {
  const localNorm = normalize(local)
  const serverNorm = normalize(server)
  const account_ids = filterValidAccountIds(
    localNorm.account_ids.length ? localNorm.account_ids : serverNorm.account_ids,
    availableAccountIds,
  )
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
