<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import { failureReasonLabel, listingStatusLabel, listingStatusType, runStatusLabel } from '@/utils/labels'
import type { Account, FailureItem, ListingFailureDetail, QueueStatus } from '@/types'

const loading = ref(false)
const queueLoading = ref(false)
const failures = ref<FailureItem[]>([])
const selectedItems = ref<FailureItem[]>([])
const detailVisible = ref(false)
const detailLoading = ref(false)
const detailItems = ref<ListingFailureDetail[]>([])
const detailTitle = ref('')
const detailRow = ref<FailureItem | null>(null)
const accounts = ref<Account[]>([])
const queue = ref<QueueStatus | null>(null)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const error = ref('')
const categoryKeyword = ref('')

const filters = reactive({
  account_id: '',
  item_status: '',
  decision_status: 'open',
  product_code: '',
})

const queueCounts = computed(() => queue.value?.counts ?? {})
const globalPaused = computed(() => Boolean(queue.value?.controls.find((c) => c.scope === 'global')?.paused))
const accountPaused = computed(() =>
  Boolean(
    filters.account_id &&
      queue.value?.controls.find((c) => c.scope === 'account' && c.account_id === filters.account_id)?.paused,
  ),
)
const selectedIds = computed(() => selectedItems.value.map((i) => i.item_id))
const hasRunningTasks = computed(() => (queueCounts.value.running || 0) > 0)

let pollTimer: ReturnType<typeof setInterval> | null = null

function failureReasonText(row: FailureItem) {
  const code = row.reason || ''
  const human = failureReasonLabel[code]
  if (human) return human
  if (row.error && row.error !== code) return row.error
  return code || '-'
}

function formatTime(t: string | null) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

function decisionLabel(status: string) {
  const map: Record<string, string> = {
    open: '待处理',
    retrying: '已提交重跑',
    handled: '已处理',
    ignored: '不再处理',
  }
  return map[status] || status
}

function decisionType(status: string) {
  if (status === 'open') return 'danger'
  if (status === 'retrying') return 'warning'
  if (status === 'handled') return 'success'
  return 'info'
}

function listingType(status: string) {
  return listingStatusType[status] || 'info'
}

async function loadQueue() {
  queueLoading.value = true
  try {
    queue.value = await api.queueStatus({ limit: 20 })
  } catch (e) {
    error.value = e instanceof Error ? e.message : '队列状态加载失败'
  } finally {
    queueLoading.value = false
  }
}

async function loadFailures() {
  loading.value = true
  error.value = ''
  try {
    const resp = await api.failures({
      page: page.value,
      page_size: pageSize.value,
      account_id: filters.account_id || undefined,
      item_status: filters.item_status || undefined,
      decision_status: filters.decision_status || undefined,
      product_code: filters.product_code || undefined,
    })
    failures.value = resp.items
    total.value = resp.total
    page.value = resp.page
    pageSize.value = resp.page_size
    if (resp.total > 0 && resp.items.length === 0 && page.value > 1) {
      page.value = 1
      await loadFailures()
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '失败项加载失败'
  } finally {
    loading.value = false
  }
}

async function loadMeta() {
  try {
    accounts.value = await api.accounts(true)
  } catch {
    accounts.value = []
  }
}

async function refreshAll() {
  await Promise.all([loadQueue(), loadFailures()])
}

async function syncFailures() {
  loading.value = true
  try {
    const resp = await api.syncFailures()
    ElMessage.success(`已同步 ${resp.upserted_items} 条失败项`)
    await loadFailures()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '同步失败项失败'
  } finally {
    loading.value = false
  }
}

async function toggleQueuePause() {
  queueLoading.value = true
  try {
    if (globalPaused.value) {
      queue.value = await api.resumeQueue('manual resume')
      ElMessage.success('队列已恢复')
    } else {
      queue.value = await api.pauseQueue('manual pause')
      ElMessage.success('队列已暂停')
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '队列控制失败'
  } finally {
    queueLoading.value = false
  }
}

async function toggleAccountPause() {
  if (!filters.account_id) {
    ElMessage.warning('请先选择一个店铺')
    return
  }
  queueLoading.value = true
  try {
    if (accountPaused.value) {
      queue.value = await api.resumeAccountQueue(filters.account_id, 'manual account resume')
      ElMessage.success(`店铺 ${filters.account_id} 队列已恢复`)
    } else {
      queue.value = await api.pauseAccountQueue(filters.account_id, 'manual account pause')
      ElMessage.success(`店铺 ${filters.account_id} 队列已暂停`)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '店铺队列控制失败'
  } finally {
    queueLoading.value = false
  }
}

async function cancelQueued(accountId = '') {
  await ElMessageBox.confirm(
    accountId ? `确认取消店铺 ${accountId} 的所有等待中任务？` : '确认取消所有等待中的队列任务？',
    '取消等待任务',
    { type: 'warning' },
  )
  const resp = await api.cancelQueuedTasks(accountId)
  ElMessage.success(`已取消 ${resp.canceled} 个等待任务`)
  await refreshAll()
}

async function cancelPending(accountId = '') {
  await ElMessageBox.confirm(
    accountId
      ? `确认停止店铺 ${accountId} 的所有运行中 + 等待中任务？`
      : '确认停止全部运行中 + 等待中的队列任务？',
    '停止全部待处理任务',
    { type: 'warning' },
  )
  const resp = await api.cancelPendingTasks(accountId)
  ElMessage.success(`已停止 ${resp.canceled} 个任务（运行+等待）`)
  await refreshAll()
}

function applyFilters() {
  page.value = 1
  loadFailures()
}

function resetFilters() {
  filters.account_id = ''
  filters.item_status = ''
  filters.decision_status = 'open'
  filters.product_code = ''
  applyFilters()
}

function onPageChange(next: number) {
  page.value = next
  loadFailures()
}

function onSizeChange(next: number) {
  pageSize.value = next
  page.value = 1
  loadFailures()
}

async function markItems(items: FailureItem[], status: string) {
  if (!items.length) return
  const label = decisionLabel(status)
  await ElMessageBox.confirm(`确认将 ${items.length} 条失败项标记为“${label}”？`, '人工处理', {
    type: 'warning',
  })
  await api.markFailuresBulk({
    item_ids: items.map((i) => i.item_id),
    decision_status: status,
    decision_note: `manual mark ${status}`,
  })
  ElMessage.success('标记完成')
  await loadFailures()
}

async function retryItems(items: FailureItem[]) {
  if (!items.length) return
  await ElMessageBox.confirm(`确认提交 ${items.length} 条失败项重跑？`, '人工重跑', {
    type: 'warning',
  })
  const resp = await api.retryFailures({
    item_ids: items.map((i) => i.item_id),
    category_keyword: categoryKeyword.value || undefined,
  })
  const queued = resp.results.filter((r) => r.status === 'queued').length
  ElMessage.success(`已提交 ${queued}/${resp.total} 条重跑`)
  await refreshAll()
}

function onSelectionChange(rows: FailureItem[]) {
  selectedItems.value = rows
}

function phaseLabel(phase: string) {
  const map: Record<string, string> = {
    preflight: '上架前校验',
    upload: '页面上架',
    price_fill: '价格表填写',
    preview: '预览图',
    submit: '提交',
    post_submit: '提交后核验',
    listing: '任务',
  }
  return map[phase] || phase || '-'
}

function formatDetailJson(detail: Record<string, unknown>) {
  if (!detail || Object.keys(detail).length === 0) return ''
  try {
    return JSON.stringify(detail, null, 2)
  } catch {
    return String(detail)
  }
}

async function loadFailureDetails(row: FailureItem, silent = false) {
  if (!silent) {
    detailLoading.value = true
    detailItems.value = []
  }
  try {
    const resp = await api.failureDetails(row.item_id)
    detailItems.value = resp.items
    if (!resp.items.length && row.source_run_id) {
      const byRun = await api.failureDetailsByRun(row.source_run_id)
      detailItems.value = byRun.items.filter(
        (d) => d.listing_label === row.listing_label || d.product_code === row.product_code,
      )
    }
  } catch (e) {
    if (!silent) {
      ElMessage.error(e instanceof Error ? e.message : '加载失败明细失败')
    }
  } finally {
    if (!silent) detailLoading.value = false
  }
}

async function showFailureDetails(row: FailureItem) {
  detailTitle.value = `${row.listing_label} — 失败明细`
  detailRow.value = row
  detailVisible.value = true
  await loadFailureDetails(row)
}

onMounted(() => {
  loadMeta()
  refreshAll()
  pollTimer = setInterval(async () => {
    if (document.hidden) return
    await loadQueue()
    if (hasRunningTasks.value) {
      await loadFailures()
      if (detailVisible.value && detailRow.value) {
        await loadFailureDetails(detailRow.value, true)
      }
    }
  }, 8000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="失败项工作台" desc="集中处理失败、跳过、可重跑的上架商品；人工确认后再单独重跑。">
      <template #actions>
        <el-button @click="syncFailures">同步失败项</el-button>
        <el-button @click="refreshAll">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="hasRunningTasks"
      type="info"
      title="有上架任务正在运行：本页每 8 秒自动刷新失败项与明细。"
      show-icon
      style="margin-bottom: 12px"
    />
    <el-alert v-if="error" type="error" :title="error" show-icon closable style="margin-bottom: 12px" @close="error = ''" />
    <el-alert
      v-if="globalPaused"
      type="warning"
      title="任务队列已暂停：等待中的上架任务不会开始，浏览器不会打开。请点击下方「恢复队列」。"
      show-icon
      style="margin-bottom: 16px"
    />

    <el-card shadow="never" class="stat-card queue-card" v-loading="queueLoading">
      <div class="queue-head">
        <div>
          <div class="queue-title">任务队列</div>
          <div class="queue-sub">
            「等待中」= 尚未开始执行；「取消运行」不会清等待任务。成功/失败为近 24 小时统计。
          </div>
        </div>
        <div class="queue-actions">
          <el-button :type="globalPaused ? 'success' : 'warning'" @click="toggleQueuePause">
            {{ globalPaused ? '恢复队列' : '暂停队列' }}
          </el-button>
          <el-button :disabled="!filters.account_id" :type="accountPaused ? 'success' : 'warning'" plain @click="toggleAccountPause">
            {{ accountPaused ? '恢复当前店铺' : '暂停当前店铺' }}
          </el-button>
          <el-button
            :disabled="!((queueCounts.queued || 0) + (queueCounts.running || 0))"
            type="danger"
            @click="cancelPending()"
          >
            停止全部（运行+等待）
          </el-button>
          <el-button
            :disabled="!filters.account_id || !(queueCounts.running || 0)"
            type="danger"
            plain
            @click="cancelPending(filters.account_id)"
          >
            停止当前店铺
          </el-button>
          <el-button :disabled="!filters.account_id" plain @click="cancelQueued(filters.account_id)">仅取消等待</el-button>
          <el-button type="danger" plain @click="cancelQueued()">取消全部等待</el-button>
        </div>
      </div>

      <el-row :gutter="12" class="queue-stats">
        <el-col :span="6">
          <div class="queue-stat">
            <strong>{{ queueCounts.queued || 0 }}</strong>
            <span>等待中</span>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="queue-stat running">
            <strong>{{ queueCounts.running || 0 }}</strong>
            <span>运行中</span>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="queue-stat success">
            <strong>{{ queueCounts.success || 0 }}</strong>
            <span>近24h成功</span>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="queue-stat danger">
            <strong>{{ queueCounts.failed || 0 }}</strong>
            <span>近24h失败</span>
          </div>
        </el-col>
      </el-row>

      <el-table v-if="queue?.tasks.length" :data="queue.tasks" size="small" stripe class="queue-table">
        <el-table-column prop="account_id" label="店铺" width="110" />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ row.agent === 'listing' ? '上架' : row.agent === 'delist' ? '下架' : row.agent }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'running' ? 'warning' : row.status === 'queued' ? 'info' : undefined">
              {{ runStatusLabel[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="计划时间" width="165">
          <template #default="{ row }">{{ formatTime(row.scheduled_at) }}</template>
        </el-table-column>
        <el-table-column prop="run_id" label="运行ID" min-width="170" show-overflow-tooltip />
        <el-table-column prop="error" label="说明" min-width="160" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-card shadow="never" class="stat-card filter-card">
      <div class="workbench-help">
        这里查询的是单个商品/套图的失败项，不是任务队列。失败后先人工确认，再选择重跑、已处理或不再处理。
      </div>
      <el-form label-position="top">
        <el-row :gutter="12">
          <el-col :span="5">
            <el-form-item label="店铺">
              <el-select v-model="filters.account_id" clearable filterable style="width: 100%">
                <el-option v-for="a in accounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="失败状态">
              <el-select v-model="filters.item_status" clearable style="width: 100%">
                <el-option label="失败" value="failed" />
                <el-option label="可重试" value="retryable" />
                <el-option label="提交不确定" value="submit_uncertain" />
                <el-option label="已跳过" value="skipped" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="人工状态">
              <el-select v-model="filters.decision_status" clearable style="width: 100%">
                <el-option label="待处理" value="open" />
                <el-option label="已提交重跑" value="retrying" />
                <el-option label="已处理" value="handled" />
                <el-option label="不再处理" value="ignored" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="5">
            <el-form-item label="商品编码">
              <el-input v-model="filters.product_code" clearable placeholder="BD046A" @keyup.enter="applyFilters" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="重跑类目关键词">
              <el-input v-model="categoryKeyword" clearable placeholder="为空则使用系统默认" />
            </el-form-item>
          </el-col>
        </el-row>
        <div class="filter-actions">
          <el-button @click="resetFilters">重置</el-button>
          <el-button type="primary" @click="applyFilters">查询</el-button>
        </div>
      </el-form>
    </el-card>

    <el-card shadow="never" class="stat-card">
      <div class="batch-bar">
        <span>已选 {{ selectedIds.length }} 条</span>
        <div>
          <el-button :disabled="!selectedIds.length" type="primary" @click="retryItems(selectedItems)">批量重跑</el-button>
          <el-button :disabled="!selectedIds.length" @click="markItems(selectedItems, 'handled')">标记已处理</el-button>
          <el-button :disabled="!selectedIds.length" type="warning" plain @click="markItems(selectedItems, 'ignored')">不再处理</el-button>
        </div>
      </div>

      <el-table :data="failures" stripe @selection-change="onSelectionChange">
        <el-table-column type="selection" width="44" />
        <el-table-column prop="account_id" label="店铺" width="110" />
        <el-table-column label="商品/套图" min-width="170">
          <template #default="{ row }">
            <div class="strong">{{ row.listing_label }}</div>
            <div class="muted">{{ row.merchant_code || row.product_code }}</div>
          </template>
        </el-table-column>
        <el-table-column label="失败状态" width="120">
          <template #default="{ row }">
            <el-tag :type="listingType(row.item_status) as any" size="small">
              {{ listingStatusLabel[row.item_status] || row.item_status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="人工状态" width="120">
          <template #default="{ row }">
            <el-tag :type="decisionType(row.decision_status) as any" size="small">
              {{ decisionLabel(row.decision_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="原因" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ failureReasonText(row) }}</template>
        </el-table-column>
        <el-table-column label="重跑任务" width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.retry_run_id || '-' }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="165">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="showFailureDetails(row)">明细</el-button>
            <el-button link type="primary" @click="retryItems([row])">重跑</el-button>
            <el-button link @click="markItems([row], 'handled')">已处理</el-button>
            <el-button link type="warning" @click="markItems([row], 'ignored')">忽略</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty
        v-if="!failures.length"
        :description="total > 0 ? '当前页无数据，已自动回到第一页；如仍为空请重新查询' : '当前筛选没有失败项，可点击同步失败项或清空筛选'"
      />
      <el-pagination
        class="pager"
        background
        layout="total, sizes, prev, pager, next, jumper"
        :total="total"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </el-card>

    <el-dialog v-model="detailVisible" :title="detailTitle" width="820px" destroy-on-close>
      <div v-loading="detailLoading">
        <el-empty v-if="!detailLoading && !detailItems.length" description="暂无失败明细（旧任务可能未写入，可重跑一次后查看）" />
        <el-timeline v-else>
          <el-timeline-item
            v-for="item in detailItems"
            :key="item.detail_id"
            :type="item.severity === 'warning' ? 'warning' : 'danger'"
            :timestamp="formatTime(item.created_at)"
            placement="top"
          >
            <div class="detail-head">
              <el-tag size="small">{{ phaseLabel(item.phase) }}</el-tag>
              <span class="detail-step">{{ item.step }}</span>
              <el-tag v-if="item.reason_code" size="small" type="info">{{ item.reason_code }}</el-tag>
            </div>
            <div class="detail-message">{{ item.message || item.error || '-' }}</div>
            <div v-if="item.error && item.message" class="detail-error muted">技术信息：{{ item.error }}</div>
            <div v-if="item.screenshot_path" class="detail-meta muted">截图：{{ item.screenshot_path }}</div>
            <div v-if="item.page_url" class="detail-meta muted">页面：{{ item.page_url }}</div>
            <pre v-if="formatDetailJson(item.detail)" class="detail-json">{{ formatDetailJson(item.detail) }}</pre>
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.queue-card,
.filter-card {
  margin-bottom: 16px;
}

.workbench-help {
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  background: #eff6ff;
  color: #1e40af;
  font-size: 13px;
}

.queue-head,
.batch-bar,
.filter-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.queue-title {
  font-weight: 700;
  color: #0f172a;
}

.queue-sub,
.muted {
  margin-top: 3px;
  font-size: 12px;
  color: var(--text-secondary);
}

.queue-actions {
  display: flex;
  gap: 8px;
}

.queue-stats {
  margin-top: 14px;
}

.queue-table {
  margin-top: 14px;
}

.queue-stat {
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: #f8fafc;
}

.queue-stat strong {
  display: block;
  font-size: 24px;
  color: #0f172a;
}

.queue-stat span {
  font-size: 12px;
  color: var(--text-secondary);
}

.queue-stat.running strong {
  color: #2563eb;
}

.queue-stat.success strong {
  color: #16a34a;
}

.queue-stat.danger strong {
  color: #dc2626;
}

.batch-bar {
  margin-bottom: 12px;
}

.strong {
  font-weight: 600;
  color: #0f172a;
}

.pager {
  margin-top: 14px;
  justify-content: flex-end;
}

.detail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.detail-step {
  font-size: 12px;
  color: var(--text-secondary);
}

.detail-message {
  font-size: 14px;
  color: #0f172a;
  line-height: 1.5;
}

.detail-error,
.detail-meta {
  margin-top: 4px;
  font-size: 12px;
}

.detail-json {
  margin-top: 8px;
  padding: 8px 10px;
  background: #f8fafc;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 12px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
