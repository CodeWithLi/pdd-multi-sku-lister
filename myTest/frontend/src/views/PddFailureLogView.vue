<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type {
  PddFailureCycleRelistAction,
  PddFailureCycleRelistCandidate,
  PddFailureCycleRelistPollCandidate,
  PddFailureCycleRelistPollLog,
  PddFailureCycleRelistTriggerPayload,
  PddFailureCycleRelistWatch,
  PddFailureLogListResponse,
  PddFailureLogRecord,
} from '@/types'

const loading = ref(false)
const watchLoading = ref(false)
const watchSaving = ref(false)
const pollLogsLoading = ref(false)
const error = ref('')
const data = ref<PddFailureLogListResponse | null>(null)
const showDebug = ref(false)
const selected = ref<PddFailureLogRecord | null>(null)
const limit = ref(100)

const watchConfig = ref<PddFailureCycleRelistWatch | null>(null)
const candidates = ref<PddFailureCycleRelistCandidate[]>([])
const pollLogs = ref<PddFailureCycleRelistPollLog[]>([])
const expandedPollId = ref('')
const triggeringRecordId = ref('')
const manualPolling = ref(false)
let watchRefreshTimer: ReturnType<typeof setInterval> | null = null

type ManualTriggerRow = Pick<
  PddFailureCycleRelistTriggerPayload,
  'record_id' | 'merchant_code' | 'account_name' | 'account_id' | 'report_platform'
>
type ManualTriggerStatusRow = ManualTriggerRow & {
  action_status?: string
  action_message?: string
  pipeline_id?: string
  cycle_relist?: string
}

const watchForm = reactive({
  enabled: false,
  poll_seconds: 60,
  completed_statuses: ['已结束', '已处理完成'] as string[],
  exclude_failure_reason_contains: '',
})

const items = computed(() => data.value?.items ?? [])
const recentActions = computed(() => watchConfig.value?.recent_actions ?? [])

const watchStatusType = computed(() => {
  if (!watchConfig.value?.enabled) return 'info'
  if (watchConfig.value.last_error) return 'error'
  if (watchConfig.value.scheduler_running) return 'success'
  return 'warning'
})

function processTagType(label: string, source: string) {
  if (source === 'empty') return 'info'
  if (!label || label === '未同步') return 'info'
  if (label.includes('完成') || label.includes('结束')) return 'success'
  if (label.includes('处理')) return 'warning'
  return 'primary'
}

function recordTypeTag(type: string) {
  if (type === '失败') return 'danger'
  if (type === '跳过') return 'warning'
  return 'info'
}

function sourceLabel(source: string) {
  const map: Record<string, string> = {
    mirror_text: '处理状态镜像',
    empty: '自动化尚未同步',
  }
  return map[source] || source
}

function actionStatusLabel(status: string) {
  const map: Record<string, string> = {
    started: '已跑链路',
    failed: '失败',
    skipped: '已跳过',
    pending: '待处理',
    waiting: '监控中',
  }
  return map[status] || status || '—'
}

function triggerSourceLabel(source: string) {
  const map: Record<string, string> = {
    auto_watch: '自动',
    manual_api: '手动',
    prime_skip: '启动忽略',
  }
  return map[source] || source || '—'
}

function fetchModeLabel(mode: string) {
  if (mode === 'list_all_fallback') return '全表回退'
  if (mode === 'search') return '条件搜索'
  return mode || '—'
}

function togglePollExpand(pollLogId: string) {
  expandedPollId.value = expandedPollId.value === pollLogId ? '' : pollLogId
}

function actionStatusType(status: string) {
  if (status === 'started') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'skipped') return 'warning'
  if (status === 'pending') return 'primary'
  return 'info'
}

function applyWatch(data: PddFailureCycleRelistWatch) {
  watchConfig.value = data
  watchForm.enabled = data.enabled
  watchForm.poll_seconds = data.poll_seconds
  watchForm.completed_statuses = [...data.completed_statuses]
  watchForm.exclude_failure_reason_contains = data.exclude_failure_reason_contains
}

async function loadWatch() {
  watchLoading.value = true
  try {
    const cfg = await api.pddFailureCycleRelistWatch()
    applyWatch(cfg)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载配置失败')
  } finally {
    watchLoading.value = false
  }
}

async function loadCandidates() {
  try {
    const resp = await api.pddFailureCycleRelistCandidates()
    if (!resp.ok) {
      ElMessage.error(resp.error || '读取候选失败')
      return
    }
    candidates.value = resp.items
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '读取候选失败')
  }
}

async function loadPollLogs() {
  pollLogsLoading.value = true
  try {
    const resp = await api.pddFailureCycleRelistPollLogs({ limit: 20 })
    if (resp.ok) {
      pollLogs.value = resp.items
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '读取拉取记录失败')
  } finally {
    pollLogsLoading.value = false
  }
}

function isTriggering(recordId: string) {
  return triggeringRecordId.value === recordId
}

function isCycleRelistSuccessText(value: string) {
  const text = String(value || '').trim()
  if (!text) return false
  return text.includes('已循环上架') || text === '是' || text.includes('已循环')
}

function manualTriggerDisabledReason(row: ManualTriggerStatusRow) {
  if (String(row.pipeline_id || '').trim()) return '已跑成功（已有链路）'
  if (String(row.action_status || '').trim() === 'started') return '已跑成功（已启动链路）'
  if (isCycleRelistSuccessText(String(row.cycle_relist || ''))) return '已跑成功（已循环上架）'
  const actionMessage = String(row.action_message || '').trim()
  if (actionMessage.includes('手动触发整合链路') || actionMessage.includes('已启动链路')) {
    return '已跑成功（已触发）'
  }
  return ''
}

function isManualTriggerBlocked(row: ManualTriggerStatusRow) {
  return !!manualTriggerDisabledReason(row)
}

async function manualTrigger(row: ManualTriggerStatusRow) {
  const recordId = row.record_id?.trim()
  if (!recordId || triggeringRecordId.value) return
  const blockedReason = manualTriggerDisabledReason(row)
  if (blockedReason) {
    ElMessage.warning(`${blockedReason}，请勿重复手动跑`)
    return
  }

  try {
    await ElMessageBox.confirm(
      `商品编码：${row.merchant_code || '—'}\n店铺：${row.account_name || '—'}\nrecord_id：${recordId}`,
      '手动跑整合链路',
      {
        confirmButtonText: '开始跑',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  triggeringRecordId.value = recordId
  try {
    const result = await api.triggerPddFailureCycleRelist({
      record_id: recordId,
      merchant_code: row.merchant_code,
      account_name: row.account_name,
      account_id: row.account_id,
      report_platform: row.report_platform,
    })
    if (result.ok && result.pipeline_id) {
      ElMessage.success(`已启动链路 ${result.pipeline_id}`)
    } else if (result.skipped) {
      ElMessage.warning(result.reason || '已跳过，未启动链路')
    } else {
      ElMessage.error(result.error || '触发失败')
    }
    await Promise.all([loadWatch(), loadCandidates(), loadPollLogs()])
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '触发失败')
  } finally {
    triggeringRecordId.value = ''
  }
}

async function manualPoll() {
  manualPolling.value = true
  try {
    const resp = await api.pollPddFailureCycleRelist()
    if (!resp.ok) {
      ElMessage.error(resp.error || '拉取失败')
      return
    }
    const total = resp.total ?? 0
    const newCount = resp.new_count ?? resp.new_items?.length ?? 0
    ElMessage.success(`拉取完成：候选 ${total} 条，新发现 ${newCount} 条（未启用自动跑时不会自动触发链路）`)
    await Promise.all([loadWatch(), loadCandidates(), loadPollLogs()])
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '拉取失败')
  } finally {
    manualPolling.value = false
  }
}

async function saveWatch() {
  watchSaving.value = true
  try {
    const cfg = await api.updatePddFailureCycleRelistWatch({
      enabled: watchForm.enabled,
      poll_seconds: watchForm.poll_seconds,
      completed_statuses: [...watchForm.completed_statuses],
      exclude_failure_reason_contains: watchForm.exclude_failure_reason_contains,
    })
    applyWatch(cfg)
    ElMessage.success(watchForm.enabled ? '已启用自动循环上架' : '已关闭自动循环上架')
    await loadCandidates()
    await loadPollLogs()
    setupWatchRefresh()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    watchSaving.value = false
  }
}

function onEnabledSwitchChange() {
  if (watchLoading.value || watchSaving.value) return
  void saveWatch()
}

function setupWatchRefresh() {
  if (watchRefreshTimer) {
    clearInterval(watchRefreshTimer)
    watchRefreshTimer = null
  }
  if (!watchConfig.value?.enabled) return
  const interval = Math.max(15, watchConfig.value.poll_seconds) * 1000
  watchRefreshTimer = setInterval(() => {
    void loadWatch()
    void loadCandidates()
    void loadPollLogs()
  }, interval)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const resp = await api.pddFailureLogs({ limit: limit.value })
    data.value = resp
    if (!resp.ok) {
      error.value = resp.error || '读取失败'
      return
    }
    if (!resp.items.length) {
      ElMessage.info('表内暂无记录')
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  } finally {
    loading.value = false
  }
}

function openDebug(row: PddFailureLogRecord) {
  selected.value = row
  showDebug.value = true
}

onMounted(async () => {
  await Promise.all([load(), loadWatch(), loadCandidates(), loadPollLogs()])
  setupWatchRefresh()
})

onUnmounted(() => {
  if (watchRefreshTimer) clearInterval(watchRefreshTimer)
})
</script>

<template>
  <div class="page">
    <PageHeader
      title="发布失败日志"
      subtitle="从飞书多维表格读取失败记录，处理状态以「处理状态镜像」列为准"
    />

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      :closable="false"
      class="mb-16"
    />

    <el-card shadow="never" class="mb-16" v-loading="watchLoading">
      <template #header>
        <div class="card-header">
          <span>自动循环上架</span>
          <div class="card-actions">
            <el-button :loading="manualPolling" @click="manualPoll">手动拉取</el-button>
            <el-button type="primary" :loading="watchSaving" @click="saveWatch">保存</el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-if="watchConfig"
        :type="watchStatusType"
        show-icon
        :closable="false"
        class="mb-12"
      >
        <template #title>
          {{
            watchConfig.enabled
              ? watchConfig.scheduler_running
                ? `运行中：每 ${watchConfig.poll_seconds} 秒轮询，新候选自动 Redis 占用并跑整合链路`
                : '已启用但调度未运行，请点保存或重启服务'
              : '未启用：仅展示候选，不会自动跑链路'
          }}
        </template>
        <template v-if="watchConfig.last_poll_at || watchConfig.last_error" #default>
          <span v-if="watchConfig.last_poll_at">
            上次轮询 {{ watchConfig.last_poll_at }} · 候选 {{ watchConfig.candidate_total }} 条 · 本轮新发现 {{ watchConfig.new_count }} 条
          </span>
          <span v-if="watchConfig.last_error" class="error-text"> · {{ watchConfig.last_error }}</span>
          <span> · <router-link to="/daily-stats">按日期查看上架/循环统计 →</router-link></span>
        </template>
      </el-alert>

      <el-form label-width="140px" class="watch-form">
        <el-form-item label="启用">
          <el-switch v-model="watchForm.enabled" @change="onEnabledSwitchChange" />
        </el-form-item>
        <el-form-item label="轮询间隔（秒）">
          <el-input-number v-model="watchForm.poll_seconds" :min="10" :max="3600" :step="10" />
        </el-form-item>
        <el-form-item label="已完成处理状态">
          <el-select
            v-model="watchForm.completed_statuses"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="已结束、已处理完成"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="排除失败原因">
          <el-input
            v-model="watchForm.exclude_failure_reason_contains"
            placeholder="失败原因包含该短语则跳过，留空不过滤"
            clearable
          />
        </el-form-item>
      </el-form>

      <el-divider content-position="left">最近处理记录</el-divider>
      <el-table
        :data="recentActions"
        stripe
        border
        size="small"
        empty-text="暂无处理记录（启用并保存后会自动轮询）"
        class="mb-16"
      >
        <el-table-column prop="at" label="时间" width="170" />
        <el-table-column prop="merchant_code" label="商品编码" width="130" show-overflow-tooltip />
        <el-table-column prop="account_name" label="店铺" width="110" show-overflow-tooltip />
        <el-table-column prop="failure_reason" label="失败原因" min-width="160" show-overflow-tooltip />
        <el-table-column prop="record_id" label="record_id" width="150" show-overflow-tooltip />
        <el-table-column label="结果" width="100">
          <template #default="{ row }: { row: PddFailureCycleRelistAction }">
            <el-tag :type="actionStatusType(row.status)" size="small">
              {{ actionStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="90">
          <template #default="{ row }: { row: PddFailureCycleRelistAction }">
            {{ triggerSourceLabel(row.trigger_source || '') }}
          </template>
        </el-table-column>
        <el-table-column prop="message" label="说明" min-width="200" show-overflow-tooltip />
        <el-table-column prop="pipeline_id" label="链路 ID" width="140" show-overflow-tooltip />
      </el-table>

      <el-divider content-position="left">最近拉取记录</el-divider>
      <el-table
        v-loading="pollLogsLoading"
        :data="pollLogs"
        stripe
        border
        size="small"
        empty-text="暂无拉取记录"
        class="mb-16"
      >
        <el-table-column prop="polled_at" label="轮询时间" width="170" />
        <el-table-column label="候选/新发现" width="110">
          <template #default="{ row }">
            {{ row.candidate_total }} / {{ row.new_count }}
          </template>
        </el-table-column>
        <el-table-column label="拉取方式" width="100">
          <template #default="{ row }">
            {{ fetchModeLabel(row.fetch_mode) }}
          </template>
        </el-table-column>
        <el-table-column prop="table_name" label="表" min-width="140" show-overflow-tooltip />
        <el-table-column label="详情" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click="togglePollExpand(row.poll_log_id)">
              {{ expandedPollId === row.poll_log_id ? '收起' : '展开' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="expandedPollId" class="poll-detail mb-16">
        <template v-for="log in pollLogs" :key="log.poll_log_id">
          <div v-if="log.poll_log_id === expandedPollId">
            <h4 v-if="log.new_candidates.length">本轮新发现（{{ log.new_candidates.length }}）</h4>
            <el-table
              v-if="log.new_candidates.length"
              :data="log.new_candidates"
              stripe
              border
              size="small"
              class="mb-12"
            >
              <el-table-column prop="merchant_code" label="商品编码" width="130" />
              <el-table-column prop="account_name" label="店铺" width="110" />
              <el-table-column prop="failure_reason" label="失败原因" min-width="180" show-overflow-tooltip />
              <el-table-column prop="process_status" label="处理状态" width="110" />
              <el-table-column prop="record_id" label="record_id" width="150" show-overflow-tooltip />
              <el-table-column label="操作" width="90" fixed="right">
                <template #default="{ row }: { row: PddFailureCycleRelistPollCandidate }">
                  <el-button
                    link
                    type="primary"
                    :loading="isTriggering(row.record_id)"
                    :disabled="isManualTriggerBlocked(row) || (!!triggeringRecordId && !isTriggering(row.record_id))"
                    :title="manualTriggerDisabledReason(row)"
                    @click="manualTrigger(row)"
                  >
                    {{ isManualTriggerBlocked(row) ? '已跑成功' : '手动跑' }}
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <h4>全部候选（{{ log.candidates.length }}）</h4>
            <el-table :data="log.candidates" stripe border size="small">
              <el-table-column prop="merchant_code" label="商品编码" width="130" />
              <el-table-column prop="account_name" label="店铺" width="110" />
              <el-table-column prop="failure_reason" label="失败原因" min-width="180" show-overflow-tooltip />
              <el-table-column prop="process_status" label="处理状态" width="110" />
              <el-table-column prop="record_id" label="record_id" width="150" show-overflow-tooltip />
              <el-table-column label="操作" width="90" fixed="right">
                <template #default="{ row }: { row: PddFailureCycleRelistPollCandidate }">
                  <el-button
                    link
                    type="primary"
                    :loading="isTriggering(row.record_id)"
                    :disabled="isManualTriggerBlocked(row) || (!!triggeringRecordId && !isTriggering(row.record_id))"
                    :title="manualTriggerDisabledReason(row)"
                    @click="manualTrigger(row)"
                  >
                    {{ isManualTriggerBlocked(row) ? '已跑成功' : '手动跑' }}
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </div>

      <el-divider content-position="left">当前候选（{{ candidates.length }}）</el-divider>
      <el-table :data="candidates" stripe border size="small" empty-text="暂无符合条件的记录">
        <el-table-column prop="date" label="日期" width="110" />
        <el-table-column prop="merchant_code" label="商品编码" width="130" show-overflow-tooltip />
        <el-table-column prop="account_name" label="店铺" width="110" show-overflow-tooltip />
        <el-table-column prop="failure_reason" label="失败原因" min-width="180" show-overflow-tooltip />
        <el-table-column prop="process_status" label="处理状态" width="110" />
        <el-table-column label="自动处理" width="110">
          <template #default="{ row }">
            <el-tag :type="actionStatusType(row.action_status)" size="small">
              {{ actionStatusLabel(row.action_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="action_message" label="原因说明" min-width="220" show-overflow-tooltip />
        <el-table-column prop="pipeline_id" label="链路 ID" width="130" show-overflow-tooltip />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }: { row: PddFailureCycleRelistCandidate }">
            <el-button
              link
              type="primary"
              :loading="isTriggering(row.record_id)"
              :disabled="isManualTriggerBlocked(row) || (!!triggeringRecordId && !isTriggering(row.record_id))"
              :title="manualTriggerDisabledReason(row)"
              @click="manualTrigger(row)"
            >
              {{ isManualTriggerBlocked(row) ? '已跑成功' : '手动跑' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="mb-16">
      <div class="toolbar">
        <div class="meta" v-if="data?.ok">
          <span>表：{{ data.table_name || '—' }}</span>
          <span>共 {{ data.total }} 条</span>
        </div>
        <div class="actions">
          <el-input-number v-model="limit" :min="1" :max="500" :step="50" />
          <el-button type="primary" :loading="loading" @click="load">刷新</el-button>
        </div>
      </div>
    </el-card>

    <el-table v-loading="loading" :data="items" stripe border style="width: 100%">
      <el-table-column prop="record_id" label="record_id" width="150" show-overflow-tooltip />
      <el-table-column prop="date" label="日期" width="110" />
      <el-table-column prop="merchant_code" label="商品编码" width="140" show-overflow-tooltip />
      <el-table-column prop="report_platform" label="报错平台" width="90" />
      <el-table-column prop="account_name" label="店铺" width="120" show-overflow-tooltip />
      <el-table-column prop="record_type" label="记录类型" width="90">
        <template #default="{ row }">
          <el-tag :type="recordTypeTag(row.record_type)" size="small">{{ row.record_type || '—' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="failure_reason" label="失败原因" min-width="220" show-overflow-tooltip />
      <el-table-column label="处理状态" width="150">
        <template #default="{ row }">
          <el-tag :type="processTagType(row.process_completed.label, row.process_completed.source)" size="small">
            {{ row.process_completed.label || '—' }}
          </el-tag>
          <div class="sub">{{ sourceLabel(row.process_completed.source) }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="cycle_relist" label="是否已循环上架" width="130" show-overflow-tooltip />
      <el-table-column prop="processor" label="人员" width="100" show-overflow-tooltip />
      <el-table-column prop="processed_at" label="处理时间" width="150" />
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }: { row: PddFailureLogRecord }">
          <el-button
            link
            type="primary"
            :loading="isTriggering(row.record_id)"
            :disabled="isManualTriggerBlocked(row) || (!!triggeringRecordId && !isTriggering(row.record_id))"
            :title="manualTriggerDisabledReason(row)"
            @click="manualTrigger(row)"
          >
            {{ isManualTriggerBlocked(row) ? '已跑成功' : '手动跑' }}
          </el-button>
          <el-button link type="primary" @click="openDebug(row)">原始数据</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="showDebug" title="原始 fields 与处理状态" size="520px">
      <template v-if="selected">
        <h4>处理状态解析</h4>
        <pre class="json-block">{{ JSON.stringify(selected.process_completed, null, 2) }}</pre>
        <h4>飞书 fields 原始值</h4>
        <pre class="json-block">{{ JSON.stringify(selected.fields_raw, null, 2) }}</pre>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.page {
  padding: 0 4px 24px;
}

.mb-16 {
  margin-bottom: 16px;
}

.mb-12 {
  margin-bottom: 12px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.card-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.watch-form {
  max-width: 640px;
}

.error-text {
  color: var(--el-color-danger);
}

.sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.json-block {
  background: #f6f8fa;
  border-radius: 6px;
  padding: 12px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
}

.poll-detail {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 12px;
}

.poll-detail h4 {
  margin: 8px 0;
  font-size: 13px;
}

h4 {
  margin: 12px 0 8px;
  font-size: 14px;
}
</style>
