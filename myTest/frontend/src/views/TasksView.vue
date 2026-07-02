<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import ResultSummary from '@/components/ResultSummary.vue'
import { useMinioMaterialRefresh } from '@/composables/useMinioMaterialRefresh'
import {
  formatMaterialGroupLabel,
  formatMaterialGroupMeta,
  groupListingTargetsByFamily,
} from '@/utils/listingTargets'
import type { Account, BatchTaskResponse, DelistTaskResponse, ListingTargetOption, ListingTaskResponse, QueueStatus } from '@/types'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const error = ref('')
const success = ref('')
const activeTab = ref('listing')

const accounts = ref<Account[]>([])
const productOptions = ref<ListingTargetOption[]>([])
const materialSource = ref<'local' | 'minio'>('minio')
const minioHealth = ref<{ available?: boolean; error?: string; listing_poll_seconds?: number; refresh_mode?: 'poll' | 'rabbitmq' } | null>(null)
const showOnlyUnlistedGroups = ref(false)
const defaultConcurrentStores = ref(3)
const defaultStartDelayMin = ref(30)
const defaultStartDelayMax = ref(180)

const accountId = ref('')
const batchAccountIds = ref<string[]>([])
const productCodes = ref<string[]>([])
const checkedProductsBySet = ref<Record<string, string[]>>({})
const selectedSetDrawerVisible = ref(false)
const activeProductDrawerSelector = ref('')
const platformListingCode = ref('')
const listingMode = ref<'check' | 'run'>('check')
const categoryKeyword = ref('玩偶')
const listingResult = ref<ListingTaskResponse | null>(null)
const listingBatchResult = ref<BatchTaskResponse | null>(null)
const listingBatchEnabled = ref(false)
const listingSlotAlignmentTest = ref(true)
const listingConcurrentStores = ref(3)
const listingStartDelayMin = ref(30)
const listingStartDelayMax = ref(180)

const delistAccountId = ref('')
const delistBatchAccountIds = ref<string[]>([])
const delistMode = ref<'scan' | 'run'>('scan')
const delistMinCreated = ref('2026-06-04 14:25')
const delistMaxPerRun = ref(1)
const delistResult = ref<DelistTaskResponse | null>(null)
const delistBatchResult = ref<BatchTaskResponse | null>(null)
const delistBatchEnabled = ref(false)
const delistConcurrentStores = ref(3)
const delistStartDelayMin = ref(30)
const delistStartDelayMax = ref(180)
const queueStatus = ref<QueueStatus | null>(null)

const {
  materialPolling,
  sseConnected,
  switchingMode,
  materialRefreshPaused,
  refreshMode,
  restart: restartMaterialRefresh,
  stop: stopMaterialRefresh,
  setMaterialRefreshPaused,
  setRefreshMode,
} = useMinioMaterialRefresh({
  materialSource,
  minioHealth,
  reloadHealth: loadMinioHealth,
  onRefresh: async () => {
    const accounts = selectedListingAccounts().filter(Boolean)
    if (accounts.length) await loadListingTargets(accounts[0])
  },
})

const enabledAccounts = computed(() => accounts.value.filter((a) => a.enabled))
const queuePaused = computed(() =>
  Boolean(queueStatus.value?.controls.find((c) => c.scope === 'global')?.paused),
)
const validProductSelectors = computed(() => new Set(productOptions.value.map((item) => item.selector)))

const unlistedGroupCount = computed(
  () => productOptions.value.filter((item) => !item.is_fully_listed).length,
)

const visibleProductOptions = computed(() => {
  if (!showOnlyUnlistedGroups.value) return productOptions.value
  return productOptions.value.filter((item) => !item.is_fully_listed)
})

const groupedVisibleProductOptions = computed(() =>
  groupListingTargetsByFamily(visibleProductOptions.value),
)

const selectedSetGroups = computed(() =>
  productCodes.value
    .map((sel) => productOptions.value.find((item) => item.selector === sel))
    .filter((item): item is ListingTargetOption => !!item),
)

const activeProductDrawerGroup = computed(
  () => selectedSetGroups.value.find((item) => item.selector === activeProductDrawerSelector.value) || null,
)

const selectedListingProductCount = computed(() =>
  selectedSetGroups.value.reduce((sum, group) => sum + selectedCountForGroup(group), 0),
)

const pendingSelectedSetCount = computed(
  () => selectedSetGroups.value.filter((group) => (group.unlisted_count ?? 0) > 0).length,
)

const resolvedListingSelectors = computed(() => {
  const result: string[] = []
  for (const group of selectedSetGroups.value) {
    const checked = checkedProductsBySet.value[group.selector] || []
    for (const code of checked) {
      if (group.product_codes.includes(code)) {
        result.push(`${group.selector}/${code}`)
      }
    }
  }
  return result
})

const allSelectedAreListed = computed(() => {
  if (!resolvedListingSelectors.value.length) return false
  return resolvedListingSelectors.value.every(isSelectorListed)
})

const listedSelectors = computed(() => resolvedListingSelectors.value.filter(isSelectorListed))

const unlistedSelectors = computed(() =>
  resolvedListingSelectors.value.filter((selector) => !isSelectorListed(selector)),
)

function isSelectorListed(selector: string) {
  const slash = selector.lastIndexOf('/')
  if (slash <= 0) return false
  const setSelector = selector.slice(0, slash)
  const code = selector.slice(slash + 1)
  const group = productOptions.value.find((item) => item.selector === setSelector)
  return !!group && isProductListed(group, code)
}

async function confirmRelistIfNeeded(): Promise<string[] | null> {
  const all = resolvedListingSelectors.value
  const listed = listedSelectors.value
  const unlisted = unlistedSelectors.value
  const isCheck = listingMode.value === 'check'

  if (!listed.length) return all

  if (!unlisted.length) {
    const labels = all.join('、')
    try {
      await ElMessageBox.confirm(
        isCheck
          ? `所选商品均已上架：\n${labels}\n\n确定仍要执行素材检查？`
          : `所选商品均已上架：\n${labels}\n\n确定要重新上架这些商品？`,
        '已上架商品',
        {
          type: 'warning',
          confirmButtonText: isCheck ? '继续检查' : '重新上架',
          cancelButtonText: '取消',
        },
      )
      return all
    } catch {
      return null
    }
  }

  const listedText = listed.join('\n')
  const unlistedText = unlisted.join('\n')
  try {
    await ElMessageBox.confirm(
      isCheck
        ? `所选同时包含已上架与未上架商品：\n\n已上架：\n${listedText}\n\n待检查：\n${unlistedText}\n\n请选择如何处理已上架商品。`
        : `所选同时包含已上架与未上架商品：\n\n已上架：\n${listedText}\n\n待上架：\n${unlistedText}\n\n请选择如何处理已上架商品。`,
      '含已上架商品',
      {
        type: 'warning',
        confirmButtonText: isCheck ? '仅检查未上架' : '仅上架未上架',
        cancelButtonText: isCheck ? '全部检查' : '全部重新上架',
        distinguishCancelAndClose: true,
      },
    )
    return unlisted
  } catch (action) {
    if (action === 'cancel') return all
    return null
  }
}

function filterValidProductCodes(codes: string[]) {
  const valid = validProductSelectors.value
  return (codes || []).filter((code) => valid.has(code))
}

function syncCheckedProductsForSets(setSelectors: string[]) {
  const next: Record<string, string[]> = { ...checkedProductsBySet.value }
  for (const sel of setSelectors) {
    const opt = productOptions.value.find((item) => item.selector === sel)
    if (!opt) continue
    const prev = next[sel] || []
    const valid = prev.filter((code) => opt.product_codes.includes(code))
    next[sel] = valid.length ? valid : [...opt.product_codes]
  }
  for (const key of Object.keys(next)) {
    if (!setSelectors.includes(key)) delete next[key]
  }
  checkedProductsBySet.value = next
}

function updateCheckedProducts(selector: string, codes: string[]) {
  checkedProductsBySet.value = { ...checkedProductsBySet.value, [selector]: codes }
}

function openProductDrawer(selector: string) {
  activeProductDrawerSelector.value = selector
}

function closeProductDrawer() {
  activeProductDrawerSelector.value = ''
}

function openSelectedSetDrawer() {
  selectedSetDrawerVisible.value = true
}

function closeSelectedSetDrawer() {
  selectedSetDrawerVisible.value = false
}

function selectAllMaterialGroups() {
  productCodes.value = visibleProductOptions.value.map((item) => item.selector)
  syncCheckedProductsForSets(productCodes.value)
}

function clearAllMaterialGroups() {
  productCodes.value = []
  checkedProductsBySet.value = {}
  closeSelectedSetDrawer()
  closeProductDrawer()
}

function selectAllListingProducts() {
  const next: Record<string, string[]> = { ...checkedProductsBySet.value }
  for (const group of selectedSetGroups.value) {
    next[group.selector] = [...group.product_codes]
  }
  checkedProductsBySet.value = next
}

function clearAllListingProducts() {
  const next: Record<string, string[]> = { ...checkedProductsBySet.value }
  for (const group of selectedSetGroups.value) {
    next[group.selector] = []
  }
  checkedProductsBySet.value = next
}

function isProductChecked(group: ListingTargetOption, code: string) {
  return (checkedProductsBySet.value[group.selector] || []).includes(code)
}

function toggleProductChecked(group: ListingTargetOption, code: string, checked: boolean) {
  const current = checkedProductsBySet.value[group.selector] || []
  const next = checked ? Array.from(new Set([...current, code])) : current.filter((item) => item !== code)
  updateCheckedProducts(group.selector, next)
}

function selectedCountForGroup(group: ListingTargetOption) {
  return (checkedProductsBySet.value[group.selector] || []).length
}

function isGroupFullySelected(group: ListingTargetOption) {
  return !!group.product_codes.length && selectedCountForGroup(group) === group.product_codes.length
}

function toggleGroupSelection(group: ListingTargetOption, shouldSelect: boolean) {
  updateCheckedProducts(group.selector, shouldSelect ? [...group.product_codes] : [])
}

function toggleGroupSelectionQuick(group: ListingTargetOption) {
  toggleGroupSelection(group, selectedCountForGroup(group) <= 0)
}

function productStatusType(group: ListingTargetOption, code: string) {
  if (isProductListed(group, code)) return 'success'
  if (isProductChecked(group, code)) return 'primary'
  return 'info'
}

function productStatusText(group: ListingTargetOption, code: string) {
  if (isProductListed(group, code)) return '已上架'
  if (isProductChecked(group, code)) return '已选中'
  return '未选中'
}

function previewProductCodes(group: ListingTargetOption) {
  const checked = checkedProductsBySet.value[group.selector] || []
  return checked.slice(0, 4)
}

function remainingPreviewCount(group: ListingTargetOption) {
  return Math.max(selectedCountForGroup(group) - previewProductCodes(group).length, 0)
}

function groupSummaryText(group: ListingTargetOption) {
  const selected = selectedCountForGroup(group)
  const total = group.product_codes.length
  const listed = group.listed_count || 0
  if (!total) return '当前套图暂无可用商品'
  if (!selected) return `共 ${total} 个商品，当前未勾选`
  return `已选 ${selected}/${total} 个商品，已上架 ${listed} 个`
}

watch(productCodes, (sets) => syncCheckedProductsForSets(sets))

function isProductListed(group: ListingTargetOption, code: string) {
  return (group.listed_product_codes || []).includes(code)
}

function onMaterialGroupDropdownVisible(visible: boolean) {
  if (!visible) return
  const accounts = selectedListingAccounts().filter(Boolean)
  if (accounts.length) loadListingTargets(accounts[0]).catch(() => undefined)
}

async function loadMinioHealth() {
  try {
    minioHealth.value = await api.minioHealth()
  } catch (e) {
    minioHealth.value = { available: false, error: e instanceof Error ? e.message : 'MinIO 不可用' }
  }
}

async function onMaterialSourceChange(source: 'local' | 'minio') {
  materialSource.value = source
  productCodes.value = []
  checkedProductsBySet.value = {}
  stopMaterialRefresh()
  if (source === 'minio') {
    await loadMinioHealth()
    if (!minioHealth.value?.available) {
      ElMessage.warning(minioHealth.value?.error || 'MinIO 未就绪，请检查 config/minio.yaml')
    }
  }
  const accounts = selectedListingAccounts().filter(Boolean)
  if (accounts.length) await loadListingTargets(accounts[0])
  restartMaterialRefresh()
}

async function loadListingTargets(forAccountId = '') {
  productOptions.value = await api.listingTargets(forAccountId || undefined, materialSource.value)
}

watch(accountId, (id) => {
  if (id) loadListingTargets(id).catch(() => undefined)
})

async function loadQueueStatus() {
  try {
    queueStatus.value = await api.queueStatus({ limit: 5 })
  } catch {
    queueStatus.value = null
  }
}

async function loadMeta() {
  try {
    const [accs, cfg] = await Promise.all([
      api.accounts(true),
      api.runtimeConfig(),
    ])
    accounts.value = accs
    categoryKeyword.value = cfg.listing.category_keyword || '玩偶'
    delistMinCreated.value = cfg.delist.min_created_after || delistMinCreated.value
    delistMaxPerRun.value = cfg.delist.max_delist_per_run || delistMaxPerRun.value
    delistMode.value = cfg.delist.dry_run ? 'scan' : 'run'
    defaultConcurrentStores.value = cfg.batch.max_concurrent_stores || 3
    defaultStartDelayMin.value = cfg.batch.store_start_delay_min_seconds ?? 30
    defaultStartDelayMax.value = cfg.batch.store_start_delay_max_seconds ?? 180
    listingConcurrentStores.value = defaultConcurrentStores.value
    delistConcurrentStores.value = defaultConcurrentStores.value
    listingStartDelayMin.value = defaultStartDelayMin.value
    listingStartDelayMax.value = defaultStartDelayMax.value
    delistStartDelayMin.value = defaultStartDelayMin.value
    delistStartDelayMax.value = defaultStartDelayMax.value

    if (accs.length && !accountId.value) {
      accountId.value = accs[0].account_id
      productCodes.value = filterValidProductCodes(accs[0].product_codes)
      syncCheckedProductsForSets(productCodes.value)
      delistAccountId.value = accs[0].account_id
      batchAccountIds.value = accs.map((a) => a.account_id)
      delistBatchAccountIds.value = accs.map((a) => a.account_id)
    }
    await loadListingTargets(accountId.value)
    await loadQueueStatus()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败，请确认后台已启动'
  }
}

function onAccountChange(id: string) {
  const acc = accounts.value.find((a) => a.account_id === id)
  productCodes.value = acc ? filterValidProductCodes(acc.product_codes) : []
  syncCheckedProductsForSets(productCodes.value)
  loadListingTargets(id).catch(() => undefined)
}

function selectedListingAccounts() {
  return listingBatchEnabled.value ? batchAccountIds.value : [accountId.value]
}

function selectedDelistAccounts() {
  return delistBatchEnabled.value ? delistBatchAccountIds.value : [delistAccountId.value]
}

function validateAccounts(ids: string[]) {
  const cleaned = ids.filter(Boolean)
  if (!cleaned.length) {
    error.value = '请至少选择一家店铺'
    return []
  }
  return cleaned
}

async function runListing() {
  const accountIds = validateAccounts(selectedListingAccounts())
  if (!accountIds.length) return
  const isCheck = listingMode.value === 'check'
  if (!productCodes.value.length) {
    error.value = '请至少选择一个素材分组'
    return
  }
  if (!resolvedListingSelectors.value.length) {
    error.value = '请至少勾选一个要上架的商品'
    return
  }
  if (!isCheck && platformListingCode.value.trim() && resolvedListingSelectors.value.length > 1) {
    error.value = '填写上架商品编码后，一次只能上架一个商品'
    return
  }
  const listingSelectors = await confirmRelistIfNeeded()
  if (!listingSelectors?.length) return

  loading.value = true
  error.value = ''
  success.value = ''
  listingResult.value = null
  listingBatchResult.value = null

  try {
    if (listingBatchEnabled.value) {
      listingBatchResult.value = await api.listingBatch({
        account_ids: accountIds,
        product_codes: listingSelectors,
        platform_listing_code: platformListingCode.value.trim(),
        dry_run: isCheck,
        category_keyword: categoryKeyword.value,
        max_concurrent_stores: listingConcurrentStores.value,
        store_start_delay_min_seconds: listingStartDelayMin.value,
        store_start_delay_max_seconds: listingStartDelayMax.value,
        slot_alignment_test: listingSlotAlignmentTest.value,
        material_source: materialSource.value,
      })
      success.value = `批量上架任务已提交：${listingBatchResult.value.total} 家店铺，并发 ${listingBatchResult.value.max_concurrent_stores} 家，启动间隔 ${listingBatchResult.value.store_start_delay_min_seconds}-${listingBatchResult.value.store_start_delay_max_seconds} 秒`
      return
    }

    listingResult.value = await api.listing({
      account_id: accountIds[0],
      product_codes: listingSelectors,
      platform_listing_code: platformListingCode.value.trim(),
      dry_run: isCheck,
      category_keyword: categoryKeyword.value,
      background: !isCheck,
      slot_alignment_test: listingSlotAlignmentTest.value,
      material_source: materialSource.value,
    })
    success.value = isCheck ? '素材检查完成' : '上架任务已提交，可在失败项工作台查看进度'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  } finally {
    loading.value = false
  }
}

async function runDelist() {
  const accountIds = validateAccounts(selectedDelistAccounts())
  if (!accountIds.length) return

  loading.value = true
  error.value = ''
  success.value = ''
  delistResult.value = null
  delistBatchResult.value = null
  const isScan = delistMode.value === 'scan'

  try {
    if (delistBatchEnabled.value) {
      delistBatchResult.value = await api.delistBatch({
        account_ids: accountIds,
        dry_run: isScan,
        min_created_after: delistMinCreated.value,
        max_delist_per_run: delistMaxPerRun.value,
        max_concurrent_stores: delistConcurrentStores.value,
        store_start_delay_min_seconds: delistStartDelayMin.value,
        store_start_delay_max_seconds: delistStartDelayMax.value,
      })
      success.value = `批量下架任务已提交：${delistBatchResult.value.total} 家店铺，并发 ${delistBatchResult.value.max_concurrent_stores} 家，启动间隔 ${delistBatchResult.value.store_start_delay_min_seconds}-${delistBatchResult.value.store_start_delay_max_seconds} 秒`
      return
    }

    delistResult.value = await api.delist({
      account_id: accountIds[0],
      dry_run: isScan,
      min_created_after: delistMinCreated.value,
      max_delist_per_run: delistMaxPerRun.value,
      background: true,
    })
    success.value = isScan ? '下架扫描任务已提交' : '下架任务已提交'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '下架失败'
  } finally {
    loading.value = false
  }
}

function goRunDetail(runId: string) {
  router.push({ path: '/runs', query: { id: runId } })
}

onMounted(async () => {
  if (route.query.tab === 'delist') activeTab.value = 'delist'
  await loadMinioHealth()
  await loadMeta()
  restartMaterialRefresh()
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="上架 / 下架"
      desc="支持单店铺与批量店铺任务；批量执行会按配置限制同时运行的店铺数。"
    />

    <el-alert v-if="error" type="error" :title="error" show-icon closable style="margin-bottom: 12px" @close="error = ''" />
    <el-alert v-if="success" type="success" :title="success" show-icon closable style="margin-bottom: 12px" @close="success = ''" />
    <el-alert
      v-if="queuePaused && listingMode === 'run'"
      type="warning"
      title="任务队列当前已暂停：上架任务会加入队列但不会执行，请到失败项工作台点击「恢复队列」。"
      show-icon
      style="margin-bottom: 12px"
    />

    <el-tabs v-model="activeTab" class="task-tabs">
      <el-tab-pane label="商品上架" name="listing">
        <div class="section-tip">
          正式上架经任务队列执行，开始后会打开浏览器。队列暂停时需先到失败项工作台恢复。
        </div>

        <el-card shadow="never" class="stat-card">
          <el-form label-position="top" class="task-form">
            <el-form-item label="批量店铺">
              <div class="batch-toggle-row">
                <el-switch v-model="listingBatchEnabled" active-text="开启" inactive-text="关闭" />
                <el-checkbox v-model="listingSlotAlignmentTest" class="slot-align-test">
                  槽位对齐（试验）
                </el-checkbox>
              </div>
              <div v-if="listingSlotAlignmentTest" class="form-tip">
                开启后：主款预览图顺序定尺寸名，兄弟款跟槽位不走尺寸并集。不满意可取消勾选，不影响原流程。
              </div>
            </el-form-item>

            <el-form-item v-if="listingBatchEnabled" label="选择店铺" required>
              <el-select v-model="batchAccountIds" multiple filterable style="width: 100%" placeholder="选择要执行的店铺">
                <el-option v-for="a in enabledAccounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
              </el-select>
            </el-form-item>

            <el-form-item v-else label="选择店铺" required>
              <el-select v-model="accountId" style="width: 100%" placeholder="请选择" @change="onAccountChange">
                <el-option v-for="a in enabledAccounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
              </el-select>
            </el-form-item>

            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="类目关键词">
                  <el-input v-model="categoryKeyword" />
                </el-form-item>
              </el-col>
              <el-col v-if="listingBatchEnabled" :span="12">
                <el-form-item label="同时运行店铺数">
                  <el-input-number v-model="listingConcurrentStores" :min="1" :max="5" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-row v-if="listingBatchEnabled" :gutter="20">
              <el-col :span="12">
                <el-form-item label="启动间隔最小秒数">
                  <el-input-number v-model="listingStartDelayMin" :min="0" :max="3600" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="启动间隔最大秒数">
                  <el-input-number
                    v-model="listingStartDelayMax"
                    :min="listingStartDelayMin"
                    :max="3600"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
            </el-row>
            <div v-if="listingBatchEnabled" class="form-tip">
              批量任务会先打开一家店，随机等待该区间后再打开下一家。
            </div>

            <div class="material-source-bar">
              <el-radio-group
                :model-value="materialSource"
                size="small"
                @change="onMaterialSourceChange($event as 'local' | 'minio')"
              >
                <el-radio-button label="local">本地文件夹</el-radio-button>
                <el-radio-button label="minio">MinIO</el-radio-button>
              </el-radio-group>
              <el-tag
                v-if="materialSource === 'minio'"
                size="small"
                :type="minioHealth?.available ? 'success' : 'danger'"
              >
                {{ minioHealth?.available ? 'MinIO 已连接' : (minioHealth?.error || 'MinIO 未连接') }}
              </el-tag>
              <el-tag v-if="materialSource === 'minio' && materialRefreshPaused" size="small" type="warning">
                已暂停拉取
              </el-tag>
              <el-tag v-else-if="materialSource === 'minio' && refreshMode === 'poll' && materialPolling" size="small" type="info">
                自动刷新
              </el-tag>
              <template v-if="materialSource === 'minio'">
                <el-radio-group
                  :model-value="refreshMode"
                  size="small"
                  :disabled="switchingMode"
                  @change="setRefreshMode($event as 'poll' | 'rabbitmq')"
                >
                  <el-radio-button label="poll">定时 {{ minioHealth?.listing_poll_seconds ?? 30 }}s</el-radio-button>
                  <el-radio-button label="rabbitmq">RabbitMQ 推送</el-radio-button>
                </el-radio-group>
                <el-switch
                  :model-value="!materialRefreshPaused"
                  inline-prompt
                  active-text="自动拉取"
                  inactive-text="已关闭"
                  @change="setMaterialRefreshPaused(!$event)"
                />
                <el-tag
                  v-if="!materialRefreshPaused && refreshMode === 'rabbitmq' && sseConnected"
                  size="small"
                  type="success"
                >
                  实时监听
                </el-tag>
                <el-tag
                  v-else-if="!materialRefreshPaused && refreshMode === 'rabbitmq'"
                  size="small"
                  type="warning"
                >
                  推送未连接
                </el-tag>
              </template>
            </div>

            <el-form-item required>
              <template #label>
                <span class="form-label-with-actions">
                  <span>素材分组</span>
                  <span class="label-actions">
                    <el-button
                      link
                      :type="showOnlyUnlistedGroups ? 'default' : 'warning'"
                      size="small"
                      @click="showOnlyUnlistedGroups = true"
                    >
                      仅未上架{{ unlistedGroupCount ? `(${unlistedGroupCount})` : '' }}
                    </el-button>
                    <el-button
                      link
                      :type="!showOnlyUnlistedGroups ? 'primary' : 'default'"
                      size="small"
                      @click="showOnlyUnlistedGroups = false"
                    >
                      全部
                    </el-button>
                    <el-button link type="primary" size="small" @click="selectAllMaterialGroups">全选</el-button>
                    <el-button link size="small" @click="clearAllMaterialGroups">取消全选</el-button>
                  </span>
                </span>
              </template>
              <el-select
                v-model="productCodes"
                multiple
                filterable
                style="width: 100%"
                :placeholder="showOnlyUnlistedGroups ? '仅显示仍有待上架商品的套图' : '选择套图（如 BD720 · 第一套图）'"
                @visible-change="onMaterialGroupDropdownVisible"
              >
                <el-option-group
                  v-for="group in groupedVisibleProductOptions"
                  :key="group.family_code"
                  :label="`${group.family_code}（${group.options.length} 套）`"
                >
                  <el-option
                    v-for="item in group.options"
                    :key="item.selector"
                    :label="formatMaterialGroupLabel(item)"
                    :value="item.selector"
                  >
                    <div class="material-option">
                      <div class="material-option-main">
                        <span class="material-option-set">{{ item.image_set }}</span>
                        <span class="material-option-meta">{{ formatMaterialGroupMeta(item) }}</span>
                      </div>
                      <div class="material-option-tags">
                        <el-tag v-if="item.is_fully_listed" size="small" type="success" class="listed-tag">已全部上架</el-tag>
                        <el-tag v-else-if="item.has_pending_listing" size="small" type="warning" class="listed-tag">
                          待上架 {{ item.unlisted_count ?? 0 }}
                        </el-tag>
                        <el-tag
                          v-else-if="item.is_material_ready === false && !(item.product_count || item.product_codes.length)"
                          size="small"
                          type="info"
                          class="listed-tag"
                        >
                          素材未就绪
                        </el-tag>
                      </div>
                    </div>
                  </el-option>
                </el-option-group>
              </el-select>
              <div v-if="showOnlyUnlistedGroups && !visibleProductOptions.length" class="form-tip">
                当前店铺暂无未上架套图
              </div>
            </el-form-item>

            <el-form-item v-if="selectedSetGroups.length" required>
              <template #label>
                <span class="form-label-with-actions">
                  <span>上架商品</span>
                  <span class="label-actions">
                    <el-button link type="primary" size="small" @click="selectAllListingProducts">全选</el-button>
                    <el-button link size="small" @click="clearAllListingProducts">取消全选</el-button>
                  </span>
                </span>
              </template>
              <div class="selection-overview-card">
                <div class="selection-overview-metrics">
                  <div class="selection-metric">
                    <span class="selection-metric-value">{{ selectedSetGroups.length }}</span>
                    <span class="selection-metric-label">已选套图</span>
                  </div>
                  <div class="selection-metric">
                    <span class="selection-metric-value">{{ selectedListingProductCount }}</span>
                    <span class="selection-metric-label">已选商品</span>
                  </div>
                  <div class="selection-metric">
                    <span class="selection-metric-value">{{ pendingSelectedSetCount }}</span>
                    <span class="selection-metric-label">待上架套图</span>
                  </div>
                </div>
                <div class="selection-overview-actions">
                  <el-button type="primary" plain size="small" @click="openSelectedSetDrawer">查看已选套图</el-button>
                  <el-button size="small" @click="selectAllListingProducts">全选商品</el-button>
                  <el-button size="small" @click="clearAllListingProducts">清空商品</el-button>
                </div>
                <div class="selection-overview-preview">
                  <el-tag v-for="group in selectedSetGroups.slice(0, 3)" :key="group.selector" effect="plain" round>
                    {{ group.family_code }} · {{ group.image_set }}
                  </el-tag>
                  <span v-if="selectedSetGroups.length > 3" class="selection-overview-more">
                    还有 {{ selectedSetGroups.length - 3 }} 套图
                  </span>
                </div>
              </div>
            </el-form-item>

            <el-form-item v-if="listingMode === 'run'" label="上架商品编码">
              <el-input v-model.trim="platformListingCode" placeholder="可选；不填则每个商品使用各自默认编码" clearable />
            </el-form-item>

            <el-form-item label="执行方式">
              <el-radio-group v-model="listingMode">
                <el-radio-button value="check">仅检查</el-radio-button>
                <el-radio-button value="run">正式上架</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-form>

          <el-button type="primary" size="large" style="width: 100%" @click="runListing">
            {{ listingBatchEnabled ? '提交批量上架' : listingMode === 'check' ? '开始检查' : '开始上架' }}
          </el-button>

          <ResultSummary
            v-if="listingResult"
            :status="listingResult.status"
            :message="listingResult.message"
            :run-id="listingResult.run_id"
            :result="listingResult.result"
            @view-detail="goRunDetail(listingResult!.run_id)"
          />

          <el-table v-if="listingBatchResult" :data="listingBatchResult.runs" size="small" stripe class="batch-table">
            <el-table-column prop="account_id" label="店铺" width="140" />
            <el-table-column prop="run_id" label="任务编号" min-width="220" />
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button link type="primary" @click="goRunDetail(row.run_id)">查看记录</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="商品下架" name="delist">
        <div class="section-tip">
          “仅扫描”不会真正下架。批量下架前建议先批量扫描，确认命中结果后再执行。
        </div>

        <el-card shadow="never" class="stat-card">
          <el-form label-position="top" class="task-form">
            <el-form-item label="批量店铺">
              <el-switch v-model="delistBatchEnabled" active-text="开启" inactive-text="关闭" />
            </el-form-item>

            <el-form-item v-if="delistBatchEnabled" label="选择店铺" required>
              <el-select v-model="delistBatchAccountIds" multiple filterable style="width: 100%" placeholder="选择要执行的店铺">
                <el-option v-for="a in enabledAccounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
              </el-select>
            </el-form-item>

            <el-form-item v-else label="选择店铺" required>
              <el-select v-model="delistAccountId" style="width: 100%" placeholder="请选择">
                <el-option v-for="a in enabledAccounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
              </el-select>
            </el-form-item>

            <el-row :gutter="20">
              <el-col :span="14">
                <el-form-item label="可下架最早创建时间">
                  <el-input v-model="delistMinCreated" placeholder="2026-06-04 14:25" />
                </el-form-item>
              </el-col>
              <el-col :span="10">
                <el-form-item label="单店最多处理数量">
                  <el-input-number v-model="delistMaxPerRun" :min="1" :max="500" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item v-if="delistBatchEnabled" label="同时运行店铺数">
              <el-input-number v-model="delistConcurrentStores" :min="1" :max="5" style="width: 100%" />
            </el-form-item>

            <el-row v-if="delistBatchEnabled" :gutter="20">
              <el-col :span="12">
                <el-form-item label="启动间隔最小秒数">
                  <el-input-number v-model="delistStartDelayMin" :min="0" :max="3600" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="启动间隔最大秒数">
                  <el-input-number
                    v-model="delistStartDelayMax"
                    :min="delistStartDelayMin"
                    :max="3600"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
            </el-row>
            <div v-if="delistBatchEnabled" class="form-tip">
              批量任务会先打开一家店，随机等待该区间后再打开下一家。
            </div>

            <el-form-item label="执行方式">
              <el-radio-group v-model="delistMode">
                <el-radio-button value="scan">仅扫描</el-radio-button>
                <el-radio-button value="run">执行下架</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-form>

          <el-button :type="delistMode === 'scan' ? 'warning' : 'danger'" size="large" style="width: 100%" @click="runDelist">
            {{ delistBatchEnabled ? '提交批量下架' : delistMode === 'scan' ? '扫描可下架商品' : '确认执行下架' }}
          </el-button>

          <ResultSummary
            v-if="delistResult"
            :status="delistResult.status"
            :message="delistResult.message"
            :run-id="delistResult.run_id"
            :result="delistResult.result"
            @view-detail="goRunDetail(delistResult!.run_id)"
          />

          <el-table v-if="delistBatchResult" :data="delistBatchResult.runs" size="small" stripe class="batch-table">
            <el-table-column prop="account_id" label="店铺" width="140" />
            <el-table-column prop="run_id" label="任务编号" min-width="220" />
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button link type="primary" @click="goRunDetail(row.run_id)">查看记录</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-drawer
      v-model="selectedSetDrawerVisible"
      title="已选套图"
      size="860px"
      append-to-body
      class="selected-set-drawer"
      @close="closeSelectedSetDrawer"
    >
      <div class="product-pick-panel">
        <div v-for="group in selectedSetGroups" :key="group.selector" class="product-pick-group">
          <div class="product-pick-group-head">
            <div class="product-pick-group-title">
              <span class="pick-family">{{ group.family_code }}</span>
              <span class="pick-set-badge">{{ group.image_set }}</span>
              <el-tag v-if="group.is_fully_listed" size="small" type="success" class="listed-tag">套图已全部上架</el-tag>
              <el-tag v-else-if="group.has_pending_listing" size="small" type="warning" class="listed-tag">
                待上架 {{ group.unlisted_count ?? 0 }} 个
              </el-tag>
              <el-tag v-else-if="(group.listed_count || 0) > 0" size="small" type="info" class="listed-tag">
                已上架 {{ group.listed_count }}/{{ group.product_codes.length }}
              </el-tag>
              <el-tag v-if="!selectedCountForGroup(group)" size="small" type="info" effect="plain">暂不上架</el-tag>
              <el-tag
                class="group-toggle-tag"
                size="small"
                :type="selectedCountForGroup(group) > 0 ? 'success' : 'info'"
                effect="light"
                @click="toggleGroupSelectionQuick(group)"
              >
                {{ selectedCountForGroup(group) > 0 ? '上架中（点设不上架）' : '不上架（点设上架）' }}
              </el-tag>
            </div>
            <div class="product-pick-group-actions">
              <el-button link type="primary" @click="openProductDrawer(group.selector)">查看商品</el-button>
            </div>
          </div>
          <div class="product-pick-group-summary">{{ groupSummaryText(group) }}</div>
          <div v-if="group.product_codes.length" class="product-pick-preview">
            <el-tag
              v-for="code in previewProductCodes(group)"
              :key="code"
              :type="productStatusType(group, code) as any"
              effect="plain"
              round
            >
              {{ code }}
            </el-tag>
            <span v-if="remainingPreviewCount(group)" class="product-pick-more">
              +{{ remainingPreviewCount(group) }} 个
            </span>
          </div>
          <div v-else class="empty-set-tip">
            套图目录已存在，但暂无可用商品（需在套图下放入带 1.jpg/1.png 等编号主图的商品文件夹）
          </div>
        </div>
      </div>
    </el-drawer>

    <el-drawer
      :model-value="!!activeProductDrawerGroup"
      size="760px"
      destroy-on-close
      append-to-body
      class="product-detail-drawer"
      @close="closeProductDrawer"
    >
      <template #header>
        <div v-if="activeProductDrawerGroup" class="product-drawer-header">
          <div class="product-drawer-title-row">
            <span class="pick-family">{{ activeProductDrawerGroup.family_code }}</span>
            <span class="pick-set-badge">{{ activeProductDrawerGroup.image_set }}</span>
          </div>
          <div class="product-drawer-meta">
            {{ groupSummaryText(activeProductDrawerGroup) }}
          </div>
        </div>
      </template>

      <div v-if="activeProductDrawerGroup" class="product-drawer-body">
        <div class="product-drawer-actions">
          <el-button size="small" @click="updateCheckedProducts(activeProductDrawerGroup.selector, [])">清空当前套图</el-button>
          <el-button
            size="small"
            type="primary"
            plain
            @click="updateCheckedProducts(activeProductDrawerGroup.selector, [...activeProductDrawerGroup.product_codes])"
          >
            全选当前套图
          </el-button>
        </div>

        <div v-if="activeProductDrawerGroup.product_codes.length" class="product-grid">
          <div
            v-for="code in activeProductDrawerGroup.product_codes"
            :key="code"
            class="product-card"
            :class="{
              'is-checked': isProductChecked(activeProductDrawerGroup, code),
              'is-listed': isProductListed(activeProductDrawerGroup, code),
            }"
            @click="toggleProductChecked(activeProductDrawerGroup, code, !isProductChecked(activeProductDrawerGroup, code))"
          >
            <div class="product-card-head">
              <el-checkbox
                :model-value="isProductChecked(activeProductDrawerGroup, code)"
                @update:model-value="(val) => toggleProductChecked(activeProductDrawerGroup!, code, Boolean(val))"
                @click.stop
              />
              <el-tag
                :type="productStatusType(activeProductDrawerGroup, code) as any"
                size="small"
                effect="light"
              >
                {{ productStatusText(activeProductDrawerGroup, code) }}
              </el-tag>
            </div>
            <div class="product-card-code">{{ code }}</div>
            <div class="product-card-foot">
              <span>点击卡片可快速切换勾选</span>
            </div>
          </div>
        </div>

        <div v-else class="empty-set-tip">
          套图目录已存在，但暂无可用商品（需在套图下放入带 1.jpg/1.png 等编号主图的商品文件夹）
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.task-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.batch-toggle-row {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.slot-align-test {
  margin: 0;
}

.task-form {
  max-width: 760px;
}

.batch-table {
  margin-top: 16px;
}

.product-pick-panel {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}

.selection-overview-card {
  width: 100%;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: linear-gradient(180deg, #fbfdff 0%, #f8fbff 100%);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.selection-overview-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
}

.selection-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 88px;
}

.selection-metric-value {
  font-size: 20px;
  line-height: 1.1;
  font-weight: 700;
  color: #0f172a;
}

.selection-metric-label {
  font-size: 12px;
  color: #64748b;
}

.selection-overview-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.selection-overview-preview {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.selection-overview-more {
  font-size: 12px;
  color: var(--text-muted);
}

.product-pick-group {
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: #fafbfd;
  min-height: 136px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.product-pick-group-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.product-pick-group-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.group-toggle-tag {
  cursor: pointer;
  user-select: none;
}

.product-pick-group-title {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.product-pick-group-summary {
  font-size: 13px;
  color: #475569;
  line-height: 1.5;
}

.product-pick-preview {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-height: 32px;
}

.product-pick-more {
  font-size: 12px;
  color: var(--text-muted);
}

.material-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.material-option-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.material-option-set {
  font-weight: 600;
  color: #1e293b;
}

.material-option-meta {
  font-size: 12px;
  color: var(--text-muted);
}

.material-option-tags {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
}

.pick-family {
  font-weight: 700;
  color: #0f172a;
}

.pick-set-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 12px;
  font-weight: 600;
}

.material-source-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.empty-set-tip {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-muted);
  padding: 4px 0;
}

.product-drawer-header {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.product-drawer-title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.product-drawer-meta {
  font-size: 13px;
  color: #64748b;
}

.product-drawer-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.product-drawer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.product-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 12px;
}

.product-card {
  border: 1px solid #dbe4f0;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
  min-height: 116px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  cursor: pointer;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;
}

.product-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.08);
  transform: translateY(-1px);
}

.product-card.is-checked {
  border-color: #60a5fa;
  background: #f8fbff;
}

.product-card.is-listed {
  background: #f0fdf4;
  border-color: #86efac;
}

.product-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.product-card-code {
  font-size: 15px;
  line-height: 1.4;
  font-weight: 700;
  color: #0f172a;
  word-break: break-all;
}

.product-card-foot {
  margin-top: auto;
  font-size: 12px;
  color: #94a3b8;
}

.listed-tag {
  margin-left: 6px;
}

.form-label-with-actions {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}

.label-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.label-actions :deep(.el-button) {
  padding: 0 4px;
  height: auto;
  font-size: 13px;
}
</style>
