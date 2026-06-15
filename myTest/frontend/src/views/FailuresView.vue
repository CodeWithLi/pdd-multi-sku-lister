<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import { listingStatusLabel, listingStatusType, runStatusLabel } from '@/utils/labels'
import type { Account, FailureItem, QueueStatus } from '@/types'

const loading = ref(false)
const queueLoading = ref(false)
const failures = ref<FailureItem[]>([])
const selectedItems = ref<FailureItem[]>([])
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

onMounted(() => {
  loadMeta()
  refreshAll()
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

    <el-alert v-if="error" type="error" :title="error" show-icon closable style="margin-bottom: 16px" @close="error = ''" />
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
        <el-table-column label="原因" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.reason || row.error || '-' }}</template>
        </el-table-column>
        <el-table-column label="重跑任务" width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.retry_run_id || '-' }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="165">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
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
</style>
