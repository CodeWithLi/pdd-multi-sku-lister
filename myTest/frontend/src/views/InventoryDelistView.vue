<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Remove, Check, Document, Upload, Shop } from '@element-plus/icons-vue'
import { inventoryDelistApi } from '@/api/inventoryDelist'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import {
  loadInventoryDelistPreferences,
  mergeInventoryDelistPreferences,
  saveInventoryDelistPreferences,
} from '@/utils/inventoryDelistPreferences'
import type { Account } from '@/types'
import type {
  InventoryDelistJob,
  InventoryDelistPreview,
  InventoryDelistRecord,
  InventoryDelistSchedule,
  InventoryRelistPreview,
  OnSaleCodesResponse,
} from '@/types/inventoryDelist'

const mainTab = ref<'delist' | 'relist'>('delist')

const router = useRouter()

const loading = ref(false)
const autoSaveState = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const previewing = ref(false)
const triggering = ref(false)
const schedule = ref<InventoryDelistSchedule | null>(null)
const accounts = ref<Account[]>([])
const preview = ref<InventoryDelistPreview | null>(null)
const relistPreview = ref<InventoryRelistPreview | null>(null)
const relistPreviewing = ref(false)
const relistPreviewTab = ref('ready')
const jobs = ref<InventoryDelistJob[]>([])
const records = ref<InventoryDelistRecord[]>([])
const formReady = ref(false)
const previewTab = ref('negative')
const shopCatalogVisible = ref(false)
const shopCatalogAccountId = ref('')
const devDialogVisible = ref(false)
const recordsDialogVisible = ref(false)
const recordsLoading = ref(false)
const recordsFilterAccount = ref('')

const onSaleCodesLoading = ref(false)
const onSaleCodeFilter = ref('')
const onSaleCodesData = ref<OnSaleCodesResponse | null>(null)
const shopPickerVisible = ref(false)
const shopPickerAccountId = ref('')
const shopPickerFilter = ref('')

let pollTimer: ReturnType<typeof setInterval> | null = null
let persistTimer: ReturnType<typeof setTimeout> | null = null
let savedHintTimer: ReturnType<typeof setTimeout> | null = null

const form = reactive({
  enabled: false,
  interval_hours: 6,
  account_ids: [] as string[],
  execution_mode: 'parallel' as 'parallel' | 'sequential',
  delist_spec_code_search_enabled: false,
  test_override_enabled: false,
  test_override_selected: [] as string[],
  test_override_default_qty: -1,
  test_delist_dry_run: true,
})

const accountLabelMap = computed(() => {
  const map = new Map<string, string>()
  for (const acc of accounts.value) {
    map.set(acc.account_id, shopDisplayName(acc))
  }
  return map
})

const statusType = computed(() => {
  if (!schedule.value?.database_available) return 'warning'
  if (!schedule.value?.enabled) return 'info'
  if (schedule.value?.scheduler_running) return 'success'
  return 'warning'
})

const selectedShopCount = computed(() => form.account_ids.length)
const isMultiShop = computed(() => selectedShopCount.value > 1)

const shopSummaryRows = computed(() => {
  if (!preview.value) return []
  return preview.value.per_account.map((row) => ({
    account_id: row.account_id,
    label: accountLabel(row.account_id),
    on_sale: row.on_sale_codes.length,
    exclusive: row.exclusive_codes?.length ?? 0,
    negative: row.negative_inventory_codes.length,
  }))
})

const negativeDetailRows = computed(() => {
  if (!preview.value) return []
  const rows: Array<{
    account_id: string
    account_label: string
    product_code: string
    available_qty: number | null
    is_common: boolean
  }> = []
  const commonSet = new Set(preview.value.common_on_sale_codes)
  for (const row of preview.value.per_account) {
    const label = accountLabel(row.account_id)
    for (const code of row.negative_inventory_codes) {
      const raw = row.inventory_by_code[code]
      rows.push({
        account_id: row.account_id,
        account_label: label,
        product_code: code,
        available_qty: raw === undefined || raw === null ? null : Number(raw),
        is_common: commonSet.has(code),
      })
    }
  }
  return rows.sort((a, b) => a.product_code.localeCompare(b.product_code, 'zh-CN'))
})

const shopCatalogLabel = computed(() => accountLabel(shopCatalogAccountId.value))

const shopCatalogCodes = computed(() => {
  if (!preview.value || !shopCatalogAccountId.value) return []
  const row = preview.value.per_account.find((item) => item.account_id === shopCatalogAccountId.value)
  return row?.on_sale_codes ?? []
})

const shopCatalogExclusive = computed(() => {
  if (!preview.value || !shopCatalogAccountId.value) return []
  const row = preview.value.per_account.find((item) => item.account_id === shopCatalogAccountId.value)
  return row?.exclusive_codes ?? []
})

const diagnosticsMessage = computed(() => String(preview.value?.diagnostics?.message || '').trim())

const diagnosticsAlertType = computed(() => {
  if (!preview.value) return 'info'
  if (preview.value.feishu_error) return 'error'
  if (!preview.value.database_available) return 'warning'
  if (!preview.value.all_on_sale_codes.length) return 'warning'
  if (!preview.value.feishu_called) return 'warning'
  return 'success'
})

const delistButtonLabel = computed(() => {
  if (form.test_override_enabled && form.test_delist_dry_run) return '模拟下架'
  return '立即下架'
})

const confirmDelistLabel = computed(() => {
  const count = preview.value?.negative_inventory_codes.length ?? 0
  const verb = form.test_override_enabled && form.test_delist_dry_run ? '模拟下架' : '确认下架'
  return count > 0 ? `${verb}（${count}）` : verb
})

const canTriggerDelist = computed(
  () => form.account_ids.length > 0 && (preview.value?.negative_inventory_codes.length ?? 0) > 0,
)

const relistReadyCount = computed(() => relistPreview.value?.relist_candidates.length ?? 0)
const relistMultiShopCount = computed(
  () => relistPreview.value?.relist_candidates.filter((row) => row.is_multi_shop).length ?? 0,
)

const relistReadyRows = computed(() => {
  if (!relistPreview.value) return []
  return relistPreview.value.relist_candidates.map((row) => ({
    product_code: row.product_code,
    available_qty: row.available_qty,
    shops:
      row.shop_names.join('、') ||
      row.account_ids.map((id) => accountLabel(id)).join('、'),
    shop_count: row.account_ids.length,
    is_multi_shop: row.is_multi_shop,
    was_common_delist: row.was_common_delist,
  }))
})

const relistStillNegativeRows = computed(() => {
  if (!relistPreview.value) return []
  return relistPreview.value.still_negative_codes.map((row) => ({
    product_code: row.product_code,
    available_qty: row.available_qty,
    shops:
      row.shop_names.join('、') ||
      row.account_ids.map((id) => accountLabel(id)).join('、'),
    shop_count: row.account_ids.length,
  }))
})

const relistDiagnosticsMessage = computed(() =>
  String(relistPreview.value?.diagnostics?.message || '').trim(),
)

const relistDiagnosticsType = computed(() => {
  if (!relistPreview.value) return 'info'
  if (relistPreview.value.feishu_error) return 'error'
  if (relistReadyCount.value > 0) return 'success'
  if ((relistPreview.value.pending_record_count ?? 0) === 0) return 'warning'
  return 'info'
})

const autoSaveHint = computed(() => {
  if (autoSaveState.value === 'saving') return '保存中…'
  if (autoSaveState.value === 'saved') return '已保存'
  if (autoSaveState.value === 'error') return '保存失败'
  return ''
})

const onSaleCodeOptions = computed(() => {
  const data = onSaleCodesData.value
  if (!data) return []
  const codeToShops = new Map<string, number>()
  for (const row of data.per_account) {
    for (const code of row.on_sale_codes) {
      const key = code.toUpperCase()
      codeToShops.set(key, (codeToShops.get(key) ?? 0) + 1)
    }
  }
  return data.all_on_sale_codes.map((code) => ({
    code,
    shopCount: codeToShops.get(code.toUpperCase()) ?? 0,
  }))
})

const filteredOnSaleCodeOptions = computed(() => {
  const q = onSaleCodeFilter.value.trim().toLowerCase()
  if (!q) return onSaleCodeOptions.value
  return onSaleCodeOptions.value.filter((item) => item.code.toLowerCase().includes(q))
})

const selectedOverrideCount = computed(() => form.test_override_selected.length)

const shopPickerAccounts = computed(() =>
  accounts.value.filter((acc) => form.account_ids.includes(acc.account_id)),
)

const shopPickerLabel = computed(() => accountLabel(shopPickerAccountId.value))

const shopPickerCodes = computed(() => {
  if (!shopPickerAccountId.value || !onSaleCodesData.value) return []
  const row = onSaleCodesData.value.per_account.find(
    (item) => item.account_id === shopPickerAccountId.value,
  )
  return row?.on_sale_codes || []
})

const shopPickerFilteredCodes = computed(() => {
  const q = shopPickerFilter.value.trim().toLowerCase()
  if (!q) return shopPickerCodes.value
  return shopPickerCodes.value.filter((code) => code.toLowerCase().includes(q))
})

function accountLabel(accountId: string) {
  return accountLabelMap.value.get(accountId) || accountId
}

function shopDisplayName(acc: Account) {
  const shop = acc.shop_display_name?.trim() || acc.display_name?.trim()
  if (shop) return shop
  const username = acc.username?.trim()
  if (username) return username
  return acc.account_id
}

function shopDisplaySub(acc: Account) {
  const shop = acc.shop_display_name?.trim() || acc.display_name?.trim()
  const username = acc.username?.trim()
  if (shop && username && shop !== username) return username
  return ''
}

function applyForm(prefs: {
  enabled: boolean
  interval_hours: number
  account_ids: string[]
  execution_mode: 'parallel' | 'sequential'
  delist_spec_code_search_enabled: boolean
  test_override_enabled?: boolean
  test_override_selected?: string[]
  test_override_default_qty?: number
  test_delist_dry_run?: boolean
}) {
  form.enabled = prefs.enabled
  form.interval_hours = prefs.interval_hours
  form.account_ids = [...prefs.account_ids]
  form.execution_mode = prefs.execution_mode
  form.delist_spec_code_search_enabled = prefs.delist_spec_code_search_enabled
  form.test_override_enabled = Boolean(prefs.test_override_enabled)
  form.test_override_selected = [...(prefs.test_override_selected || [])]
  form.test_override_default_qty = Number.isFinite(Number(prefs.test_override_default_qty))
    ? Number(prefs.test_override_default_qty)
    : -1
  form.test_delist_dry_run = prefs.test_delist_dry_run !== false
}

function testPayload() {
  const overrides: Record<string, number> = {}
  if (form.test_override_enabled) {
    const qty = form.test_override_default_qty ?? -1
    for (const code of form.test_override_selected) {
      const trimmed = code.trim()
      if (trimmed) overrides[trimmed] = qty
    }
  }
  return {
    test_override_enabled: form.test_override_enabled,
    test_inventory_overrides: overrides,
    test_override_text: '',
  }
}

function persistLocalPreferences() {
  saveInventoryDelistPreferences({
    enabled: form.enabled,
    interval_hours: form.interval_hours,
    account_ids: form.account_ids,
    execution_mode: form.execution_mode,
    delist_spec_code_search_enabled: form.delist_spec_code_search_enabled,
    test_override_enabled: form.test_override_enabled,
    test_override_selected: form.test_override_selected,
    test_override_default_qty: form.test_override_default_qty,
    test_delist_dry_run: form.test_delist_dry_run,
  })
}

function schedulePersistToServer() {
  if (!formReady.value) return
  persistLocalPreferences()
  if (persistTimer) clearTimeout(persistTimer)
  persistTimer = setTimeout(() => void persistToServer(), 600)
}

async function persistToServer() {
  autoSaveState.value = 'saving'
  try {
    const data = await inventoryDelistApi.updateSchedule({
      enabled: form.enabled,
      interval_hours: form.interval_hours,
      account_ids: form.account_ids,
      execution_mode: form.execution_mode,
      delist_spec_code_search_enabled: form.delist_spec_code_search_enabled,
    })
    schedule.value = data
    autoSaveState.value = 'saved'
    if (savedHintTimer) clearTimeout(savedHintTimer)
    savedHintTimer = setTimeout(() => {
      if (autoSaveState.value === 'saved') autoSaveState.value = 'idle'
    }, 2000)
  } catch {
    autoSaveState.value = 'error'
  }
}

function toggleShop(accountId: string, checked: boolean) {
  const set = new Set(form.account_ids)
  if (checked) set.add(accountId)
  else set.delete(accountId)
  form.account_ids = [...set]
}

function selectAllShops() {
  form.account_ids = accounts.value.map((acc) => acc.account_id)
}

function clearShops() {
  form.account_ids = []
}

async function loadOnSaleCodes() {
  if (!form.account_ids.length) return
  onSaleCodesLoading.value = true
  try {
    onSaleCodesData.value = await inventoryDelistApi.onSaleCodes(form.account_ids)
    const available = new Set(
      onSaleCodesData.value.all_on_sale_codes.map((code) => code.toUpperCase()),
    )
    form.test_override_selected = form.test_override_selected.filter((code) =>
      available.has(code.toUpperCase()),
    )
  } catch (e) {
    onSaleCodesData.value = null
    ElMessage.error(e instanceof Error ? e.message : '加载在售编码失败')
  } finally {
    onSaleCodesLoading.value = false
  }
}

function toggleOverrideCode(code: string, checked: boolean) {
  const set = new Set(form.test_override_selected)
  if (checked) set.add(code)
  else set.delete(code)
  form.test_override_selected = [...set]
}

async function openShopPicker(accountId?: string) {
  if (!form.account_ids.length) return
  if (!onSaleCodesData.value && !onSaleCodesLoading.value) await loadOnSaleCodes()
  if (!onSaleCodesData.value) return
  shopPickerFilter.value = ''
  shopPickerAccountId.value =
    accountId && form.account_ids.includes(accountId) ? accountId : form.account_ids[0]
  shopPickerVisible.value = true
}

async function openDevDialog() {
  devDialogVisible.value = true
  if (form.account_ids.length) await loadOnSaleCodes()
}

function openShopCatalog(accountId: string) {
  shopCatalogAccountId.value = accountId
  shopCatalogVisible.value = true
}

async function loadJobs() {
  const result = await inventoryDelistApi.jobs(15)
  jobs.value = result.items
}

async function loadRecords(accountId?: string) {
  try {
    const result = await inventoryDelistApi.records({
      account_id: accountId || undefined,
      limit: 100,
    })
    records.value = result.items
  } catch {
    records.value = []
  }
}

async function openRecordsDialog() {
  recordsDialogVisible.value = true
  recordsFilterAccount.value = form.account_ids.length === 1 ? form.account_ids[0] : ''
  await loadRecordsForDialog()
}

async function loadRecordsForDialog() {
  recordsLoading.value = true
  try {
    await loadRecords(recordsFilterAccount.value || undefined)
  } finally {
    recordsLoading.value = false
  }
}

async function load() {
  loading.value = true
  formReady.value = false
  try {
    const [cfg, accs] = await Promise.all([
      inventoryDelistApi.schedule(),
      api.accounts(true),
    ])
    accounts.value = accs
    const merged = mergeInventoryDelistPreferences(
      cfg,
      loadInventoryDelistPreferences(),
      accs,
    )
    applyForm(merged)
    schedule.value = cfg
    persistLocalPreferences()
    await loadJobs()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
    formReady.value = true
  }
}

async function refreshScheduleMeta() {
  try {
    schedule.value = await inventoryDelistApi.schedule()
  } catch {
    // ignore
  }
}

async function runPreview() {
  if (!form.account_ids.length) {
    ElMessage.warning('请至少选择一个店铺')
    return
  }
  previewing.value = true
  try {
    preview.value = await inventoryDelistApi.preview(form.account_ids, {
      force_feishu_refresh: true,
      ...testPayload(),
    })
    previewTab.value =
      (preview.value.negative_inventory_codes.length ?? 0) > 0 ? 'negative' : 'summary'
    const neg = preview.value.negative_inventory_codes.length
    const common = preview.value.common_on_sale_codes.length
    ElMessage.success(
      neg > 0
        ? `检测完成：共同上架 ${common} 个，待下架 ${neg} 个`
        : `检测完成：共同上架 ${common} 个，无负库存商品`,
    )
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '检测失败')
  } finally {
    previewing.value = false
  }
}

async function runRelistPreview() {
  if (!form.account_ids.length) {
    ElMessage.warning('请至少选择一个店铺')
    return
  }
  relistPreviewing.value = true
  try {
    relistPreview.value = await inventoryDelistApi.relistPreview(form.account_ids, {
      force_feishu_refresh: true,
    })
    relistPreviewTab.value = relistReadyCount.value > 0 ? 'ready' : 'pending'
    const ready = relistReadyCount.value
    const pending = relistPreview.value.pending_record_count
    ElMessage.success(
      ready > 0
        ? `检测完成：${pending} 条待恢复记录，${ready} 个编码可上架`
        : `检测完成：${pending} 条待恢复记录，暂无可用数已恢复的编码`,
    )
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '恢复检测失败')
  } finally {
    relistPreviewing.value = false
  }
}

async function submitDelist(options?: { requirePreview?: boolean }) {
  if (!form.account_ids.length) {
    ElMessage.warning('请至少选择一个店铺')
    return
  }
  const negCount = preview.value?.negative_inventory_codes.length ?? 0
  if (options?.requirePreview && negCount === 0) {
    ElMessage.warning('当前无待下架商品，请先检测预览')
    return
  }

  const isDryRun = form.test_override_enabled && form.test_delist_dry_run
  if (!isDryRun) {
    const message =
      negCount > 0
        ? `将对 ${form.account_ids.length} 家店铺的 ${negCount} 个负库存商品执行下架（仅下架，不上架），确定继续？`
        : `将重新检测并下架负库存商品，确定继续？`
    try {
      await ElMessageBox.confirm(message, '确认下架', {
        type: 'warning',
        confirmButtonText: '立即下架',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
  }

  triggering.value = true
  try {
    const result = await inventoryDelistApi.trigger({
      account_ids: form.account_ids,
      execution_mode: form.execution_mode,
      delist_spec_code_search_enabled: form.delist_spec_code_search_enabled,
      ...testPayload(),
      delist_dry_run: isDryRun,
    })
    ElMessage.success(`已启动下架任务：${result.job.job_id}${isDryRun ? '（模拟）' : ''}`)
    await loadJobs()
    router.push('/runs')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '触发失败')
  } finally {
    triggering.value = false
  }
}

function jobStatusType(status: string) {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function recordStatusType(status: string) {
  if (status === 'completed') return 'success'
  if (status === 'dry_run') return 'warning'
  if (status === 'failed') return 'danger'
  if (status === 'skipped' || status === 'not_found') return 'info'
  return ''
}

function recordStatusLabel(status: string) {
  const map: Record<string, string> = {
    completed: '已下架',
    dry_run: '模拟',
    failed: '失败',
    skipped: '跳过',
    not_found: '未找到',
  }
  return map[status] || status
}

function qtyClass(qty: number | null) {
  if (qty === null) return 'qty-unknown'
  if (qty < 0) return 'qty-negative'
  return 'qty-ok'
}

onMounted(() => {
  load()
  pollTimer = setInterval(() => {
    loadJobs().catch(() => {})
    refreshScheduleMeta().catch(() => {})
  }, 15000)
})

watch(
  () => ({ ...form }),
  () => schedulePersistToServer(),
  { deep: true },
)

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (persistTimer) clearTimeout(persistTimer)
  if (savedHintTimer) clearTimeout(savedHintTimer)
})
</script>

<template>
  <div v-loading="loading" class="page">
    <PageHeader
      title="负库存管理"
      desc="下架：扫描在售商品，聚水潭可用数 &lt; 0 时自动下架。恢复上架：对已下架记录查聚水潭，可用数恢复后联动多店重新上架。"
    >
      <template #actions>
        <el-button :icon="Document" @click="openRecordsDialog">下架记录</el-button>
        <template v-if="mainTab === 'delist'">
          <el-button :loading="previewing" type="primary" :icon="Search" @click="runPreview">
            检测预览
          </el-button>
          <el-button
            :loading="triggering"
            type="warning"
            :icon="Remove"
            :disabled="!canTriggerDelist && !form.test_override_enabled"
            @click="submitDelist({ requirePreview: !form.test_override_enabled })"
          >
            {{ delistButtonLabel }}
          </el-button>
        </template>
        <template v-else>
          <el-button :loading="relistPreviewing" type="primary" :icon="Search" @click="runRelistPreview">
            恢复检测
          </el-button>
          <el-button type="success" :icon="Upload" disabled>立即上架（即将支持）</el-button>
        </template>
      </template>
    </PageHeader>

    <el-card shadow="never" class="mb-16 shop-panel">
      <template #header>
        <div class="card-head">
          <span><el-icon class="head-icon"><Shop /></el-icon> 选择店铺</span>
          <span class="shop-panel__actions">
            <span class="hint">已选 {{ selectedShopCount }} / {{ accounts.length }} 家</span>
            <el-button link type="primary" size="small" @click="selectAllShops">全选</el-button>
            <el-button link type="info" size="small" @click="clearShops">清空</el-button>
          </span>
        </div>
      </template>
      <div class="shop-grid">
        <button
          v-for="acc in accounts"
          :key="acc.account_id"
          type="button"
          class="shop-card"
          :class="{ 'shop-card--active': form.account_ids.includes(acc.account_id) }"
          @click="toggleShop(acc.account_id, !form.account_ids.includes(acc.account_id))"
        >
          <span class="shop-card__name">{{ shopDisplayName(acc) }}</span>
          <span v-if="shopDisplaySub(acc)" class="shop-card__sub">{{ shopDisplaySub(acc) }}</span>
          <el-icon v-if="form.account_ids.includes(acc.account_id)" class="shop-card__check"><Check /></el-icon>
        </button>
      </div>
    </el-card>

    <el-tabs v-model="mainTab" class="main-tabs mb-16">
      <el-tab-pane label="负库存下架" name="delist">
        <el-alert v-if="schedule" :type="statusType" show-icon :closable="false" class="mb-16">
          <template #title>
            {{ schedule.scheduler_running ? '下架定时调度运行中' : '下架定时调度未运行' }}
          </template>
          <template #default>
            {{
              schedule.enabled
                ? `已启用：每 ${schedule.interval_hours} 小时自动检测并下架负库存商品`
                : '定时未启用，可手动检测预览后下架'
            }}
            <span v-if="schedule.last_scheduled_run_at"> · 上次：{{ schedule.last_scheduled_run_at }}</span>
          </template>
        </el-alert>

        <el-card shadow="never" class="mb-16">
          <template #header>
            <div class="card-head">
              <span>下架配置</span>
              <span v-if="autoSaveHint" class="hint">{{ autoSaveHint }}</span>
            </div>
          </template>
          <el-form label-width="96px" class="config-form">
            <el-form-item label="定时间隔">
              <div class="inline">
                <el-switch v-model="form.enabled" />
                <template v-if="form.enabled">
                  <span>每</span>
                  <el-input-number
                    v-model="form.interval_hours"
                    :min="0.5"
                    :max="168"
                    :step="0.5"
                    :precision="1"
                    controls-position="right"
                    style="width: 120px"
                  />
                  <span>小时执行</span>
                </template>
              </div>
            </el-form-item>

            <el-form-item label="执行方式">
              <el-radio-group v-model="form.execution_mode">
                <el-radio label="parallel">多店同时下架</el-radio>
                <el-radio label="sequential">逐店下架</el-radio>
              </el-radio-group>
            </el-form-item>

            <el-form-item label="高级选项">
              <el-checkbox v-model="form.delist_spec_code_search_enabled">
                商品编码未命中时尝试规格编码搜索（较慢）
              </el-checkbox>
              <el-button link type="info" size="small" class="dev-link" @click="openDevDialog">
                开发者联调
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

    <el-card shadow="never" class="mb-16">
      <template #header>
        <span>下架检测预览</span>
      </template>

      <div v-if="!preview" class="preview-empty">
        <p>流程：读取各店已上架商品 → 整合共同/独有编码 → 查飞书聚水潭可用数 → 列出可用数 &lt; 0 的商品</p>
        <el-button type="primary" :loading="previewing" :icon="Search" @click="runPreview">
          开始检测
        </el-button>
      </div>

      <template v-else>
        <el-alert
          :type="diagnosticsAlertType"
          :closable="false"
          show-icon
          class="mb-12"
          :title="diagnosticsMessage || '检测完成'"
        />

        <el-table :data="shopSummaryRows" size="small" border stripe class="mb-16">
          <el-table-column prop="label" label="店铺" min-width="140" />
          <el-table-column prop="on_sale" label="在售数" width="88" align="center" />
          <el-table-column prop="exclusive" label="独有" width="72" align="center">
            <template #default="{ row }">
              <el-button
                v-if="row.exclusive > 0"
                link
                type="primary"
                size="small"
                @click="openShopCatalog(row.account_id)"
              >
                {{ row.exclusive }}
              </el-button>
              <span v-else>0</span>
            </template>
          </el-table-column>
          <el-table-column prop="negative" label="待下架" width="88" align="center">
            <template #default="{ row }">
              <el-text :type="row.negative ? 'danger' : undefined">{{ row.negative }}</el-text>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="88" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openShopCatalog(row.account_id)">
                在售
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="preview-toolbar">
          <el-tabs v-model="previewTab" class="preview-tabs">
            <el-tab-pane
              :label="`待下架 (${preview.negative_inventory_codes.length})`"
              name="negative"
            >
              <el-table :data="negativeDetailRows" size="small" border stripe empty-text="无负库存商品">
                <el-table-column prop="account_label" label="店铺" width="140" />
                <el-table-column prop="product_code" label="商品编码" min-width="160" />
                <el-table-column label="可用数" width="100" align="center">
                  <template #default="{ row }">
                    <span :class="qtyClass(row.available_qty)">{{ row.available_qty ?? '—' }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="多店共同" width="96" align="center">
                  <template #default="{ row }">
                    {{ row.is_common ? '是' : '否' }}
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <el-tab-pane
              v-if="isMultiShop"
              :label="`共同上架 (${preview.common_on_sale_codes.length})`"
              name="common"
            >
              <div class="code-list">
                <el-tag
                  v-for="code in preview.common_on_sale_codes"
                  :key="code"
                  size="small"
                  effect="plain"
                >
                  {{ code }}
                </el-tag>
                <el-empty v-if="!preview.common_on_sale_codes.length" description="无共同上架商品" />
              </div>
            </el-tab-pane>

            <el-tab-pane
              v-for="row in preview.per_account"
              :key="row.account_id"
              :label="`${accountLabel(row.account_id)}独有 (${row.exclusive_codes?.length ?? 0})`"
              :name="`exclusive-${row.account_id}`"
            >
              <div class="code-list">
                <el-tag
                  v-for="code in row.exclusive_codes || []"
                  :key="code"
                  size="small"
                  type="info"
                  effect="plain"
                >
                  {{ code }}
                </el-tag>
                <el-empty v-if="!(row.exclusive_codes?.length)" description="该店无独有商品" />
              </div>
            </el-tab-pane>
          </el-tabs>

          <el-button
            type="warning"
            :icon="Remove"
            :loading="triggering"
            :disabled="!canTriggerDelist"
            class="preview-delist-btn"
            @click="submitDelist({ requirePreview: true })"
          >
            {{ confirmDelistLabel }}
          </el-button>
        </div>
      </template>
    </el-card>

    <el-card shadow="never">
      <template #header>最近任务</template>
      <el-table :data="jobs" size="small" stripe>
        <el-table-column prop="job_id" label="任务 ID" min-width="180" show-overflow-tooltip />
        <el-table-column prop="trigger" label="触发" width="72" />
        <el-table-column prop="status" label="状态" width="88">
          <template #default="{ row }">
            <el-tag :type="jobStatusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="店铺" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.account_ids.map(accountLabel).join('、') }}</template>
        </el-table-column>
        <el-table-column label="待下架" width="72" align="center">
          <template #default="{ row }">
            <el-text :type="row.negative_inventory_codes.length ? 'danger' : undefined">
              {{ row.negative_inventory_codes.length }}
            </el-text>
          </template>
        </el-table-column>
        <el-table-column label="方式" width="72">
          <template #default="{ row }">
            {{ row.execution_mode === 'parallel' ? '同时' : '逐店' }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="160" />
        <el-table-column prop="message" label="说明" min-width="140" show-overflow-tooltip />
      </el-table>
      <el-empty v-if="!jobs.length" description="暂无任务" :image-size="56" />
    </el-card>
      </el-tab-pane>

      <el-tab-pane label="库存恢复上架" name="relist">
        <el-alert type="info" show-icon :closable="false" class="mb-16">
          <template #title>多店联动规则</template>
          <template #default>
            读取「已下架且未重新上架」记录，查聚水潭当前可用数。同一商品若在多家店铺同时下架，可用数恢复后需<strong>全部店铺一起上架</strong>。浏览器自动上架功能下一步实现。
          </template>
        </el-alert>

        <el-row :gutter="12" class="stat-row mb-16">
          <el-col :xs="24" :sm="8">
            <div class="stat-card">
              <div class="stat-card__label">待恢复记录</div>
              <div class="stat-card__value">{{ relistPreview?.pending_record_count ?? '—' }}</div>
            </div>
          </el-col>
          <el-col :xs="24" :sm="8">
            <div class="stat-card stat-card--success">
              <div class="stat-card__label">可上架编码</div>
              <div class="stat-card__value">{{ relistReadyCount || '—' }}</div>
            </div>
          </el-col>
          <el-col :xs="24" :sm="8">
            <div class="stat-card stat-card--warning">
              <div class="stat-card__label">多店联动</div>
              <div class="stat-card__value">{{ relistMultiShopCount || '—' }}</div>
            </div>
          </el-col>
        </el-row>

        <el-card shadow="never" class="mb-16">
          <template #header>
            <div class="card-head">
              <span>恢复上架配置</span>
              <el-tag size="small" type="info" effect="plain">定时任务 · 即将支持</el-tag>
            </div>
          </template>
          <el-form label-width="96px" class="config-form">
            <el-form-item label="定时间隔">
              <div class="inline">
                <el-switch :model-value="false" disabled />
                <span class="text-muted">恢复上架定时检测（下一步实现）</span>
              </div>
            </el-form-item>
            <el-form-item label="恢复条件">
              <span>聚水潭可用数 ≥ 0</span>
            </el-form-item>
          </el-form>
        </el-card>

        <el-card shadow="never">
          <template #header>
            <span>恢复检测预览</span>
          </template>

          <div v-if="!relistPreview" class="preview-empty">
            <p>流程：读取已下架记录 → 查聚水潭可用数 → 列出可用数已恢复的商品 → 多店联动展示</p>
            <el-button type="primary" :loading="relistPreviewing" :icon="Search" @click="runRelistPreview">
              开始检测
            </el-button>
          </div>

          <template v-else>
            <el-alert
              :type="relistDiagnosticsType"
              :closable="false"
              show-icon
              class="mb-12"
              :title="relistDiagnosticsMessage || '检测完成'"
            />

            <el-tabs v-model="relistPreviewTab">
              <el-tab-pane :label="`可上架 (${relistReadyCount})`" name="ready">
                <el-table :data="relistReadyRows" size="small" border stripe empty-text="暂无可用数已恢复的编码">
                  <el-table-column prop="product_code" label="商品编码" min-width="120" />
                  <el-table-column label="当前可用数" width="100" align="center">
                    <template #default="{ row }">
                      <span :class="qtyClass(row.available_qty)">{{ row.available_qty ?? '—' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="shops" label="需上架店铺" min-width="180" show-overflow-tooltip />
                  <el-table-column label="店铺数" width="80" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" :type="row.is_multi_shop ? 'warning' : 'info'" effect="plain">
                        {{ row.shop_count }} 家
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="共同下架" width="96" align="center">
                    <template #default="{ row }">
                      <el-tag v-if="row.was_common_delist" size="small" type="warning" effect="plain">是</el-tag>
                      <span v-else class="text-muted">否</span>
                    </template>
                  </el-table-column>
                </el-table>
              </el-tab-pane>

              <el-tab-pane
                :label="`仍负库存 (${relistPreview.still_negative_codes.length})`"
                name="negative"
              >
                <el-table
                  :data="relistStillNegativeRows"
                  size="small"
                  border
                  stripe
                  empty-text="无仍负库存的待恢复编码"
                >
                  <el-table-column prop="product_code" label="商品编码" min-width="120" />
                  <el-table-column label="当前可用数" width="100" align="center">
                    <template #default="{ row }">
                      <span class="qty-negative">{{ row.available_qty ?? '—' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="shops" label="待恢复店铺" min-width="180" show-overflow-tooltip />
                  <el-table-column prop="shop_count" label="店铺数" width="80" align="center" />
                </el-table>
              </el-tab-pane>

              <el-tab-pane
                :label="`待恢复编码 (${relistPreview.unique_product_codes.length})`"
                name="pending"
              >
                <div class="code-list">
                  <el-tag
                    v-for="code in relistPreview.unique_product_codes"
                    :key="code"
                    size="small"
                    :type="relistPreview.common_pending_codes.includes(code) ? 'warning' : 'info'"
                    effect="plain"
                  >
                    {{ code }}
                    <span v-if="relistPreview.common_pending_codes.includes(code)"> · 多店</span>
                  </el-tag>
                  <el-empty v-if="!relistPreview.unique_product_codes.length" description="暂无待恢复编码" />
                </div>
              </el-tab-pane>
            </el-tabs>
          </template>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="recordsDialogVisible"
      title="负库存下架记录"
      width="960px"
      class="records-dialog"
      destroy-on-close
    >
      <div class="records-toolbar">
        <el-select
          v-model="recordsFilterAccount"
          clearable
          placeholder="全部店铺"
          style="width: 200px"
          @change="loadRecordsForDialog"
        >
          <el-option
            v-for="acc in accounts"
            :key="acc.account_id"
            :label="shopDisplayName(acc)"
            :value="acc.account_id"
          />
        </el-select>
        <span class="records-toolbar__hint">共 {{ records.length }} 条</span>
        <el-button :loading="recordsLoading" @click="loadRecordsForDialog">刷新</el-button>
      </div>
      <el-table
        v-loading="recordsLoading"
        :data="records"
        size="small"
        stripe
        border
        max-height="520"
        empty-text="暂无下架记录"
      >
        <el-table-column prop="delisted_at" label="下架时间" width="160" fixed />
        <el-table-column prop="shop_display_name" label="店铺" min-width="120" show-overflow-tooltip />
        <el-table-column prop="product_code" label="商品编码" min-width="110" />
        <el-table-column label="可用数" width="80" align="center">
          <template #default="{ row }">
            <span :class="qtyClass(row.erp_available_qty)">{{ row.erp_available_qty ?? '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="原可用数" width="88" align="center">
          <template #default="{ row }">
            <span v-if="row.is_test_override">{{ row.erp_original_qty ?? '—' }}</span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="88" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="recordStatusType(row.delist_status)">
              {{ recordStatusLabel(row.delist_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="重新上架" width="88" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_relisted ? 'success' : 'info'" effect="plain">
              {{ row.is_relisted ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标记" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.is_test_override" size="small" type="warning" effect="plain">测试</el-tag>
            <el-tag v-if="row.dry_run" size="small" type="info" effect="plain">dry_run</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="trigger" label="触发" width="72" />
        <el-table-column prop="message" label="说明" min-width="140" show-overflow-tooltip />
      </el-table>
    </el-dialog>

    <!-- 某店在售商品 -->
    <el-dialog v-model="shopCatalogVisible" :title="`${shopCatalogLabel} · 已上架商品`" width="520px">
      <p class="dialog-desc">
        在售 {{ shopCatalogCodes.length }} 个
        <span v-if="isMultiShop"> · 其中独有 {{ shopCatalogExclusive.length }} 个</span>
      </p>
      <div class="code-list code-list--scroll">
        <el-tag v-for="code in shopCatalogCodes" :key="code" size="small" effect="plain">{{ code }}</el-tag>
      </div>
    </el-dialog>

    <!-- 开发者联调 -->
    <el-dialog v-model="devDialogVisible" title="开发者联调" width="640px">
      <el-alert type="warning" :closable="false" show-icon class="mb-12">
        仅用于联调：先真实查飞书，再人为改写指定编码可用数；不影响定时任务逻辑。
      </el-alert>
      <el-form label-width="100px">
        <el-form-item label="测试覆盖">
          <el-switch v-model="form.test_override_enabled" />
        </el-form-item>
        <template v-if="form.test_override_enabled">
          <el-form-item label="覆盖编码">
            <div v-loading="onSaleCodesLoading" class="override-box">
              <div class="override-toolbar">
                <el-input v-model="onSaleCodeFilter" clearable placeholder="搜索" size="small" />
                <el-button size="small" @click="openShopPicker()">按店铺选</el-button>
                <span>可用数</span>
                <el-input-number
                  v-model="form.test_override_default_qty"
                  size="small"
                  controls-position="right"
                  style="width: 100px"
                />
              </div>
              <el-checkbox-group v-model="form.test_override_selected" class="code-group">
                <el-checkbox
                  v-for="item in filteredOnSaleCodeOptions"
                  :key="item.code"
                  :label="item.code"
                >
                  {{ item.code }}
                </el-checkbox>
              </el-checkbox-group>
            </div>
          </el-form-item>
          <el-form-item label="dry_run">
            <el-switch v-model="form.test_delist_dry_run" />
          </el-form-item>
        </template>
      </el-form>
    </el-dialog>

    <el-dialog v-model="shopPickerVisible" :title="`选择编码 · ${shopPickerLabel}`" width="520px">
      <el-select v-model="shopPickerAccountId" style="width: 100%; margin-bottom: 12px">
        <el-option
          v-for="acc in shopPickerAccounts"
          :key="acc.account_id"
          :label="shopDisplayName(acc)"
          :value="acc.account_id"
        />
      </el-select>
      <el-input v-model="shopPickerFilter" clearable placeholder="搜索编码" class="mb-12" />
      <div class="picker-grid">
        <button
          v-for="code in shopPickerFilteredCodes"
          :key="code"
          type="button"
          class="picker-item"
          :class="{ on: form.test_override_selected.includes(code) }"
          @click="toggleOverrideCode(code, !form.test_override_selected.includes(code))"
        >
          {{ code }}
          <el-icon v-if="form.test_override_selected.includes(code)"><Check /></el-icon>
        </button>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  padding-bottom: 24px;
}

.main-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.head-icon {
  vertical-align: -2px;
  margin-right: 4px;
}

.shop-panel__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.shop-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}

.shop-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}

.shop-card:hover {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.08);
}

.shop-card--active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.shop-card__name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.shop-card__sub {
  font-size: 12px;
  color: #909399;
}

.shop-card__check {
  position: absolute;
  top: 10px;
  right: 10px;
  color: var(--el-color-primary);
}

.stat-row .el-col {
  margin-bottom: 8px;
}

.stat-card {
  padding: 14px 16px;
  border-radius: 8px;
  background: linear-gradient(135deg, #f5f7fa 0%, #eef1f6 100%);
  border: 1px solid var(--el-border-color-lighter);
}

.stat-card--success {
  background: linear-gradient(135deg, #f0f9eb 0%, #e8f5e1 100%);
  border-color: #e1f3d8;
}

.stat-card--warning {
  background: linear-gradient(135deg, #fdf6ec 0%, #faecd8 100%);
  border-color: #faecd8;
}

.stat-card__label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}

.stat-card__value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}

.mb-16 {
  margin-bottom: 16px;
}

.mb-12 {
  margin-bottom: 12px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.hint {
  font-size: 12px;
  color: #909399;
  font-weight: normal;
}

.config-form :deep(.el-form-item) {
  margin-bottom: 18px;
}

.inline {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.shop-box {
  width: 100%;
  max-width: 480px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 8px 12px;
}

.shop-box__toolbar {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 13px;
  color: #606266;
}

.shop-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.shop-sub {
  margin-left: 6px;
  font-size: 12px;
  color: #909399;
}

.dev-link {
  margin-left: 12px;
}

.preview-empty {
  text-align: center;
  padding: 24px 16px;
  color: #606266;
}

.preview-empty p {
  margin: 0 0 16px;
  font-size: 14px;
  line-height: 1.6;
}

.preview-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.preview-tabs {
  flex: 1;
  min-width: 0;
}

.preview-delist-btn {
  flex-shrink: 0;
  margin-top: 4px;
}

.code-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 48px;
}

.code-list--scroll {
  max-height: 360px;
  overflow-y: auto;
}

.qty-negative {
  color: var(--el-color-danger);
  font-weight: 600;
}

.qty-unknown {
  color: #909399;
}

.dialog-desc {
  margin: 0 0 12px;
  font-size: 13px;
  color: #606266;
}

.override-box {
  width: 100%;
}

.override-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.override-toolbar .el-input {
  flex: 1;
  min-width: 120px;
}

.code-group {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  max-height: 200px;
  overflow-y: auto;
}

.picker-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 8px;
  max-height: 320px;
  overflow-y: auto;
}

.picker-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
}

.picker-item.on {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.records-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.records-toolbar__hint {
  flex: 1;
  font-size: 13px;
  color: #909399;
}

.text-muted {
  color: #c0c4cc;
}
</style>
