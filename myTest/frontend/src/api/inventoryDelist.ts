import axios from 'axios'
import type {
  InventoryDelistJob,
  InventoryDelistPreview,
  InventoryRelistJob,
  InventoryRelistPreview,
  InventoryDelistRecord,
  InventoryDelistSchedule,
  OnSaleCodesResponse,
} from '@/types/inventoryDelist'

const http = axios.create({
  baseURL: '/api',
  timeout: 300_000,
})

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const detail = err?.response?.data?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((item: { msg?: string }) => item.msg || '').filter(Boolean).join('；')
          : err?.response?.data?.error || err?.message || '请求失败'
    return Promise.reject(new Error(message))
  },
)

export const inventoryDelistApi = {
  schedule: () =>
    http.get<InventoryDelistSchedule>('/inventory-delist/schedule').then((r) => r.data),

  updateSchedule: (body: Partial<InventoryDelistSchedule>) =>
    http.put<InventoryDelistSchedule>('/inventory-delist/schedule', body).then((r) => r.data),

  preview: (
    account_ids: string[],
    options?: {
      force_feishu_refresh?: boolean
      test_override_enabled?: boolean
      test_inventory_overrides?: Record<string, number>
      test_override_text?: string
    },
  ) =>
    http
      .post<InventoryDelistPreview>('/inventory-delist/preview', {
        account_ids,
        force_feishu_refresh: options?.force_feishu_refresh ?? true,
        test_override_enabled: options?.test_override_enabled ?? false,
        test_inventory_overrides: options?.test_inventory_overrides ?? {},
        test_override_text: options?.test_override_text ?? '',
      })
      .then((r) => r.data),

  relistPreview: (
    account_ids: string[],
    options?: { force_feishu_refresh?: boolean; min_available_qty?: number },
  ) =>
    http
      .post<InventoryRelistPreview>('/inventory-delist/relist/preview', {
        account_ids,
        force_feishu_refresh: options?.force_feishu_refresh ?? true,
        min_available_qty: options?.min_available_qty ?? 0,
      })
      .then((r) => r.data),

  relistTrigger: (body: {
    account_ids?: string[]
    product_codes?: string[]
    execution_mode?: 'parallel' | 'sequential'
    force_feishu_refresh?: boolean
    min_available_qty?: number
    relist_dry_run?: boolean
  }) =>
    http
      .post<{ ok: boolean; job: InventoryRelistJob }>('/inventory-delist/relist/trigger', body)
      .then((r) => r.data),

  relistJobs: (limit = 20) =>
    http
      .get<{ ok: boolean; total: number; items: InventoryRelistJob[] }>(
        '/inventory-delist/relist/jobs',
        { params: { limit } },
      )
      .then((r) => r.data),

  relistJob: (jobId: string) =>
    http.get<InventoryRelistJob>(`/inventory-delist/relist/jobs/${jobId}`).then((r) => r.data),

  trigger: (body: {
    account_ids?: string[]
    execution_mode?: 'parallel' | 'sequential'
    delist_spec_code_search_enabled?: boolean
    test_override_enabled?: boolean
    test_inventory_overrides?: Record<string, number>
    test_override_text?: string
    delist_dry_run?: boolean
  }) =>
    http
      .post<{ ok: boolean; job: InventoryDelistJob }>('/inventory-delist/trigger', body)
      .then((r) => r.data),

  jobs: (limit = 20) =>
    http
      .get<{ ok: boolean; total: number; items: InventoryDelistJob[] }>('/inventory-delist/jobs', {
        params: { limit },
      })
      .then((r) => r.data),

  job: (jobId: string) =>
    http.get<InventoryDelistJob>(`/inventory-delist/jobs/${jobId}`).then((r) => r.data),

  onSaleCodes: (account_ids: string[]) =>
    http
      .post<OnSaleCodesResponse>('/inventory-delist/on-sale-codes', { account_ids })
      .then((r) => r.data),

  records: (params?: { account_id?: string; job_id?: string; limit?: number }) =>
    http
      .get<{ ok: boolean; total: number; items: InventoryDelistRecord[] }>(
        '/inventory-delist/records',
        { params },
      )
      .then((r) => r.data),
}
