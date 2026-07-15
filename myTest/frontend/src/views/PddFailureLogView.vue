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
  FailureSequentialJob,
  FailureSequentialStuckJob,
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

const FAILURE_LOG_READ_TABLE_KEY = 'pdd_agent.failure_log.read_table_enabled'

function loadReadFailureTablePref(): boolean {
  try {
    const raw = localStorage.getItem(FAILURE_LOG_READ_TABLE_KEY)
    if (raw === '0' || raw === 'false') return false
    if (raw === '1' || raw === 'true') return true
  } catch {
    // ignore
  }
  return true
}

function saveReadFailureTablePref(enabled: boolean) {
  try {
    localStorage.setItem(FAILURE_LOG_READ_TABLE_KEY, enabled ? '1' : '0')
  } catch {
    // ignore
  }
}

/** 是否读取下方「全平台发布日志表（失败）」；关闭后不请求飞书表 */
const readFailureTableEnabled = ref(loadReadFailureTablePref())

const watchConfig = ref<PddFailureCycleRelistWatch | null>(null)
const candidates = ref<PddFailureCycleRelistCandidate[]>([])
const pollLogs = ref<PddFailureCycleRelistPollLog[]>([])
const expandedPollId = ref('')
const triggeringRecordId = ref('')
const manualPolling = ref(false)
const dismissBlockerLoading = ref(false)
const clearRecentActionsLoading = ref(false)
const sequentialJobsLoading = ref(false)
const sequentialJobs = ref<FailureSequentialJob[]>([])
const sequentialBatchActive = ref(false)
const stuckJobsLoading = ref(false)
const resetStuckLoading = ref(false)
const stuckJobs = ref<FailureSequentialStuckJob[]>([])
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
  exclude_failure_reason_contains: [] as string[],
  fetch_after_date: '',
  sequential_staged_enabled: false,
  sequential_activity_delay_minutes: 5,
  attach_source_pipeline_enabled: false,
  capture_pipeline_id_enabled: false,
})

const excludeReasonDraft = ref('')

function addExcludeFailureReason(raw?: string) {
  const text = String(raw ?? excludeReasonDraft.value ?? '').trim()
  if (!text) {
    ElMessage.warning('请先输入要排除的失败原因短语')
    return
  }
  if (watchForm.exclude_failure_reason_contains.includes(text)) {
    ElMessage.warning('该排除短语已存在')
    excludeReasonDraft.value = ''
    return
  }
  watchForm.exclude_failure_reason_contains.push(text)
  excludeReasonDraft.value = ''
  void saveWatch({ successMessage: '排除失败原因已保存' })
}

function removeExcludeFailureReason(index: number) {
  if (index < 0 || index >= watchForm.exclude_failure_reason_contains.length) return
  watchForm.exclude_failure_reason_contains.splice(index, 1)
  void saveWatch({ successMessage: '排除失败原因已保存' })
}

const items = computed(() => data.value?.items ?? [])
const recentActions = computed(() => watchConfig.value?.recent_actions ?? [])

const attachPathReady = computed(
  () =>
    Boolean(watchForm.attach_source_pipeline_enabled) &&
    Boolean(watchForm.capture_pipeline_id_enabled),
)

const statusSummaryTitle = computed(() => {
  const cfg = watchConfig.value
  if (!cfg) return '加载配置中…'
  if (!cfg.enabled) return '未启用：仅可查看候选，不会自动处理'
  if (cfg.sequential_staged_enabled) {
    return cfg.sequential_scheduler_running
      ? `分阶段运行中 · 每 ${cfg.poll_seconds}s 一条`
      : '分阶段已启用，但调度未运行（请保存或重启服务）'
  }
  if (!cfg.scheduler_running) return '已启用，但调度未运行（请保存或重启服务）'
  if (attachPathReady.value) {
    return `挂回原链路运行中 · 每 ${cfg.poll_seconds}s 轮询 · 仅处理含链路 ID 的记录`
  }
  return `循环上架运行中 · 每 ${cfg.poll_seconds}s 轮询（新建整合链路）`
})

const candidatesEmptyText = computed(() => {
  if (!watchForm.enabled) {
    return '尚未启用自动处理。打开上方「启用」并保存后，符合条件的失败项会出现在这里。'
  }
  if (attachPathReady.value) {
    return '暂无待处理候选。请检查：抓取时间、排除原因、处理状态筛选，以及系统原因是否含 [pipeline:…]。'
  }
  return '暂无符合条件的候选。可点「手动拉取」，或检查抓取时间、排除失败原因与处理状态。'
})

function candidateRowClassName({ row }: { row: PddFailureCycleRelistCandidate }) {
  if (attachPathReady.value && !String(row.source_pipeline_id || '').trim()) {
    return 'row-missing-pipeline'
  }
  return ''
}

const morePanels = ref<string[]>([])

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
    waiting: '等待中',
  }
  return map[status] || status || '—'
}

function triggerSourceLabel(source: string) {
  const map: Record<string, string> = {
    auto_watch: '自动',
    manual_api: '手动',
    manual_dismiss: '解除阻塞',
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
  if (status === 'waiting') return 'info'
  return 'info'
}

const hasCycleRelistBlocker = computed(() =>
  Boolean(watchConfig.value?.cycle_relist_blocker_pipeline_id),
)

async function dismissCycleRelistBlocker() {
  const pid = watchConfig.value?.cycle_relist_blocker_pipeline_id || ''
  const stale = Boolean(watchConfig.value?.cycle_relist_blocker_stale)
  const hint = stale
    ? `检测到僵尸链路 ${pid}（已超过 6 小时未更新），解除后将标为失败并允许重新处理。`
    : `将终止阻塞链路 ${pid}，相关「等待中」记录会标为失败，下一轮可重新跑。`
  try {
    await ElMessageBox.confirm(hint, '解除循环上架阻塞', {
      type: 'warning',
      confirmButtonText: '解除阻塞',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  dismissBlockerLoading.value = true
  try {
    const resp = await api.dismissPddFailureCycleRelistBlocker(
      pid ? { pipeline_id: pid } : {},
    )
    if (!resp.ok) {
      ElMessage.error(resp.error || '解除阻塞失败')
      return
    }
    ElMessage.success(
      resp.message ||
        `已解除阻塞（${resp.dismissed_records ?? 0} 条记录已标为失败）`,
    )
    await Promise.all([loadWatch(), loadCandidates()])
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '解除阻塞失败')
  } finally {
    dismissBlockerLoading.value = false
  }
}

async function clearRecentActions() {
  if (!recentActions.value.length) {
    ElMessage.info('当前没有最近处理记录')
    return
  }
  try {
    await ElMessageBox.confirm(
      '将清空页面上的「最近处理记录」（含库中历史动作日志），不影响候选列表和轮询本身。确定清除？',
      '清除最近处理记录',
      {
        type: 'warning',
        confirmButtonText: '清除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  clearRecentActionsLoading.value = true
  try {
    const resp = await api.clearPddFailureCycleRelistRecentActions()
    if (!resp.ok) {
      ElMessage.error(resp.error || '清除失败')
      return
    }
    if (watchConfig.value) {
      watchConfig.value = { ...watchConfig.value, recent_actions: [] }
    }
    ElMessage.success(
      resp.message ||
        `已清除（内存 ${resp.cleared_memory ?? 0} 条，库表 ${resp.cleared_db ?? 0} 条）`,
    )
    await loadWatch()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '清除失败')
  } finally {
    clearRecentActionsLoading.value = false
  }
}

function applyWatch(data: PddFailureCycleRelistWatch) {
  watchConfig.value = data
  watchForm.enabled = data.enabled
  watchForm.poll_seconds = data.poll_seconds
  watchForm.completed_statuses = [...data.completed_statuses]
  watchForm.exclude_failure_reason_contains = [...(data.exclude_failure_reason_contains || [])]
  watchForm.fetch_after_date = String(data.fetch_after_date || '')
  watchForm.sequential_staged_enabled = Boolean(data.sequential_staged_enabled)
  watchForm.sequential_activity_delay_minutes = Number(data.sequential_activity_delay_minutes ?? 5)
  watchForm.attach_source_pipeline_enabled = Boolean(data.attach_source_pipeline_enabled)
  watchForm.capture_pipeline_id_enabled = Boolean(data.capture_pipeline_id_enabled)
}

function stageStatusLabel(status: string) {
  const map: Record<string, string> = {
    pending: '待处理',
    running: '运行中',
    success: '成功',
    failed: '失败',
    skipped: '已跳过',
  }
  return map[status] || status || '—'
}

function stageStatusType(status: string) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'skipped') return 'warning'
  if (status === 'running') return 'primary'
  return 'info'
}

async function loadStuckJobs() {
  stuckJobsLoading.value = true
  try {
    const resp = await api.pddFailureSequentialStuckJobs({ limit: 100 })
    stuckJobs.value = resp.items ?? []
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载卡死任务失败')
  } finally {
    stuckJobsLoading.value = false
  }
}

async function loadSequentialJobs() {
  sequentialJobsLoading.value = true
  try {
    const resp = await api.pddFailureSequentialJobs({ limit: 100 })
    sequentialJobs.value = resp.items ?? []
    sequentialBatchActive.value = Boolean(resp.batch_active)
    await loadStuckJobs()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载分阶段任务失败')
  } finally {
    sequentialJobsLoading.value = false
  }
}

async function resetStuckSequentialJobs() {
  if (!stuckJobs.value.length) {
    ElMessage.info('当前没有卡死的运行中任务')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将把 ${stuckJobs.value.length} 条卡死任务重置为「待处理」，调度器会在下一轮继续执行。`,
      '重置卡死任务',
      {
        type: 'warning',
        confirmButtonText: '重置',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  resetStuckLoading.value = true
  try {
    const resp = await api.resetPddFailureSequentialStuckJobs({ limit: 100 })
    ElMessage.success(`已重置 ${resp.reset_count} 条卡死任务`)
    await loadSequentialJobs()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '重置卡死任务失败')
  } finally {
    resetStuckLoading.value = false
  }
}

function stuckStageSummary(row: FailureSequentialStuckJob) {
  return (row.stuck_stages ?? [])
    .map((stage) => stage.label || stage.stage)
    .filter(Boolean)
    .join('、')
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

async function saveWatch(options?: { successMessage?: string }) {
  watchSaving.value = true
  try {
    const cfg = await api.updatePddFailureCycleRelistWatch({
      enabled: watchForm.enabled,
      poll_seconds: watchForm.poll_seconds,
      completed_statuses: [...watchForm.completed_statuses],
      exclude_failure_reason_contains: [...watchForm.exclude_failure_reason_contains],
      fetch_after_date: watchForm.fetch_after_date || '',
      sequential_staged_enabled: watchForm.sequential_staged_enabled,
      sequential_activity_delay_minutes: watchForm.sequential_activity_delay_minutes,
      attach_source_pipeline_enabled: watchForm.attach_source_pipeline_enabled,
      capture_pipeline_id_enabled: watchForm.capture_pipeline_id_enabled,
    })
    applyWatch(cfg)
    if (options?.successMessage) {
      ElMessage.success(options.successMessage)
    } else {
      const mode = watchForm.sequential_staged_enabled
        ? '分阶段流水线（上架→限时限量购→活动→推广）'
        : watchForm.attach_source_pipeline_enabled && watchForm.capture_pipeline_id_enabled
          ? '挂回原链路（抓取链路 ID）'
          : '整合链路'
      ElMessage.success(
        watchForm.enabled ? `已启用自动循环上架（${mode}）` : '已关闭自动循环上架',
      )
    }
    await Promise.all([loadCandidates(), loadPollLogs(), loadSequentialJobs()])
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

function onFetchAfterDateChange(value: string | null) {
  watchForm.fetch_after_date = value ? String(value) : ''
  if (watchLoading.value || watchSaving.value) return
  void saveWatch({ successMessage: '抓取时间已保存' })
}

function onAttachSourcePipelineChange(value: boolean | string | number) {
  if (!value) {
    watchForm.capture_pipeline_id_enabled = false
  }
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
    if (watchConfig.value?.sequential_staged_enabled) {
      void loadSequentialJobs()
    }
  }, interval)
}

async function load() {
  if (!readFailureTableEnabled.value) {
    data.value = null
    error.value = ''
    ElMessage.info('已关闭读取失败表，不请求飞书数据')
    return
  }
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

function onReadFailureTableChange(value: boolean | string | number) {
  const enabled = Boolean(value)
  readFailureTableEnabled.value = enabled
  saveReadFailureTablePref(enabled)
  if (!enabled) {
    data.value = null
    error.value = ''
    ElMessage.success('已关闭读取失败表')
    return
  }
  void load()
}

function openDebug(row: PddFailureLogRecord) {
  selected.value = row
  showDebug.value = true
}

onMounted(async () => {
  const boot = [loadWatch(), loadCandidates(), loadPollLogs(), loadSequentialJobs()]
  if (readFailureTableEnabled.value) {
    boot.unshift(load())
  }
  await Promise.all(boot)
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
      subtitle="按规则自动/手动处理失败项；挂回原链路需同时开启「抓取链路 ID」"
    />

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      :closable="false"
      class="mb-16"
    />

    <!-- 1. 顶部状态 + 精简规则 -->
    <el-card shadow="never" class="mb-16" v-loading="watchLoading">
      <template #header>
        <div class="card-header">
          <span>处理规则</span>
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
        <template #title>{{ statusSummaryTitle }}</template>
        <template #default>
          <span v-if="watchConfig.last_poll_at">
            上次轮询 {{ watchConfig.last_poll_at }} · 候选 {{ watchConfig.candidate_total }} · 新发现
            {{ watchConfig.new_count }}
          </span>
          <span v-else>尚未轮询</span>
          <span v-if="attachPathReady" class="mode-chip"> · 挂回原链路已齐</span>
          <span
            v-else-if="watchForm.attach_source_pipeline_enabled && !watchForm.capture_pipeline_id_enabled"
            class="warn-text"
          >
            · 已开挂回，请再开「抓取链路 ID」
          </span>
          <span v-if="watchConfig.last_error" class="error-text"> · {{ watchConfig.last_error }}</span>
          <span>
            · <router-link to="/daily-stats">日报统计 →</router-link>
          </span>
        </template>
      </el-alert>

      <el-alert
        v-if="hasCycleRelistBlocker"
        :type="watchConfig?.cycle_relist_blocker_stale ? 'warning' : 'error'"
        show-icon
        :closable="false"
        class="mb-12"
      >
        <template #title>
          {{
            watchConfig?.cycle_relist_blocker_stale
              ? `僵尸链路阻塞：${watchConfig?.cycle_relist_blocker_pipeline_id}（${watchConfig?.cycle_relist_blocker_age_hours}h）`
              : `链路阻塞中：${watchConfig?.cycle_relist_blocker_pipeline_id}`
          }}
        </template>
        <template #default>
          <span>候选会卡在「等待中」。确认没在跑时可解除阻塞。</span>
          <el-button
            class="ml-12"
            type="danger"
            size="small"
            :loading="dismissBlockerLoading"
            @click="dismissCycleRelistBlocker"
          >
            解除阻塞
          </el-button>
        </template>
      </el-alert>

      <el-form label-width="120px" class="watch-form rules-compact">
        <el-form-item label="启用">
          <el-switch v-model="watchForm.enabled" @change="onEnabledSwitchChange" />
        </el-form-item>

        <el-form-item label="挂回原链路">
          <div class="switch-pair">
            <el-switch
              v-model="watchForm.attach_source_pipeline_enabled"
              :disabled="!watchForm.enabled || watchForm.sequential_staged_enabled"
              active-text="开"
              inactive-text="关"
              @change="onAttachSourcePipelineChange"
            />
            <el-switch
              v-model="watchForm.capture_pipeline_id_enabled"
              :disabled="
                !watchForm.enabled ||
                watchForm.sequential_staged_enabled ||
                !watchForm.attach_source_pipeline_enabled
              "
              active-text="抓取链路 ID"
              inactive-text="不抓取"
              @change="onEnabledSwitchChange"
            />
          </div>
          <div class="form-hint">
            两开关都开才挂回原链路重跑（上架→限时→活动改期）；无 [pipeline:…] 的条目会跳过。
          </div>
        </el-form-item>

        <el-form-item label="抓取时间">
          <el-date-picker
            v-model="watchForm.fetch_after_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="仅抓取该日及之后（飞书「日期」）"
            clearable
            style="width: 260px"
            @change="onFetchAfterDateChange"
          />
          <div class="form-hint">
            按飞书失败表「日期」字段筛选：只处理 >= 该日的记录；清空则不过滤日期。
          </div>
        </el-form-item>

        <el-form-item label="排除失败原因">
          <div class="exclude-reason-editor">
            <div class="exclude-reason-input-row">
              <el-input
                v-model="excludeReasonDraft"
                clearable
                placeholder="短语：包含即不进候选，回车或点添加"
                @keydown.enter.prevent="addExcludeFailureReason()"
              />
              <el-button type="primary" @click="addExcludeFailureReason()">添加</el-button>
            </div>
            <div v-if="watchForm.exclude_failure_reason_contains.length" class="exclude-reason-tags">
              <el-tag
                v-for="(phrase, index) in watchForm.exclude_failure_reason_contains"
                :key="`${phrase}-${index}`"
                closable
                class="exclude-reason-tag"
                @close="removeExcludeFailureReason(index)"
              >
                {{ phrase }}
              </el-tag>
            </div>
            <div v-else class="form-hint">暂无排除短语（添加/删除后自动保存）</div>
          </div>
        </el-form-item>

        <el-collapse class="more-settings">
          <el-collapse-item title="更多设置（轮询 / 处理状态 / 分阶段）" name="more-settings">
            <el-form-item label="分阶段流水线">
              <el-switch
                v-model="watchForm.sequential_staged_enabled"
                :disabled="!watchForm.enabled"
                active-text="分阶段（不走整合链路）"
                inactive-text="关闭"
                @change="onEnabledSwitchChange"
              />
            </el-form-item>
            <el-form-item v-if="watchForm.sequential_staged_enabled" label="活动延迟(分)">
              <el-input-number
                v-model="watchForm.sequential_activity_delay_minutes"
                :min="0"
                :max="10080"
                :step="1"
              />
            </el-form-item>
            <el-form-item label="轮询间隔(秒)">
              <el-input-number v-model="watchForm.poll_seconds" :min="10" :max="3600" :step="10" />
            </el-form-item>
            <el-form-item label="已完成状态">
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
          </el-collapse-item>
        </el-collapse>
      </el-form>
    </el-card>

    <!-- 2. 主工作区：当前待处理候选 -->
    <el-card shadow="never" class="mb-16 primary-work">
      <template #header>
        <div class="card-header">
          <span>当前待处理候选（{{ candidates.length }}）</span>
          <el-button size="small" :loading="manualPolling" @click="manualPoll">刷新候选</el-button>
        </div>
      </template>

      <el-table
        :data="candidates"
        stripe
        border
        size="small"
        :empty-text="candidatesEmptyText"
        :row-class-name="candidateRowClassName"
      >
        <el-table-column prop="merchant_code" label="商品编码" width="130" show-overflow-tooltip />
        <el-table-column prop="account_name" label="店铺" width="110" show-overflow-tooltip />
        <el-table-column prop="failure_reason" label="失败原因" min-width="180" show-overflow-tooltip />
        <el-table-column label="原链路 ID" width="160" show-overflow-tooltip>
          <template #default="{ row }: { row: PddFailureCycleRelistCandidate }">
            <span v-if="row.source_pipeline_id">{{ row.source_pipeline_id }}</span>
            <span v-else class="muted">无（挂回模式下将跳过）</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="actionStatusType(row.action_status)" size="small">
              {{ actionStatusLabel(row.action_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="action_message" label="说明" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }: { row: PddFailureCycleRelistCandidate }">
            <el-button
              link
              type="primary"
              :loading="isTriggering(row.record_id)"
              :disabled="
                isManualTriggerBlocked(row) || (!!triggeringRecordId && !isTriggering(row.record_id))
              "
              :title="manualTriggerDisabledReason(row)"
              @click="manualTrigger(row)"
            >
              {{ isManualTriggerBlocked(row) ? '已跑成功' : '手动跑' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 3. 最近处理结果 -->
    <el-card shadow="never" class="mb-16">
      <template #header>
        <div class="card-header">
          <span>最近处理结果（{{ recentActions.length }}）</span>
          <el-button
            type="danger"
            plain
            size="small"
            :loading="clearRecentActionsLoading"
            :disabled="!recentActions.length"
            @click="clearRecentActions"
          >
            清除记录
          </el-button>
        </div>
      </template>

      <el-table
        :data="recentActions"
        stripe
        border
        size="small"
        empty-text="暂无处理结果。启用并轮询后，成功/跳过/失败会出现在这里。"
      >
        <el-table-column prop="at" label="时间" width="170" />
        <el-table-column prop="merchant_code" label="商品编码" width="130" show-overflow-tooltip />
        <el-table-column prop="account_name" label="店铺" width="110" show-overflow-tooltip />
        <el-table-column label="结果" width="100">
          <template #default="{ row }: { row: PddFailureCycleRelistAction }">
            <el-tag :type="actionStatusType(row.status)" size="small">
              {{ actionStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="说明" min-width="220" show-overflow-tooltip />
        <el-table-column prop="pipeline_id" label="链路 ID" width="150" show-overflow-tooltip />
      </el-table>
    </el-card>

    <!-- 4. 更多 / 调试（默认收起） -->
    <el-card shadow="never" class="mb-16">
      <el-collapse v-model="morePanels">
        <el-collapse-item
          v-if="watchForm.sequential_staged_enabled"
          title="分阶段任务进度"
          name="sequential"
        >
          <div v-loading="stuckJobsLoading" class="stuck-reset-panel mb-12">
            <el-button
              type="warning"
              :loading="resetStuckLoading"
              :disabled="!stuckJobs.length"
              @click="resetStuckSequentialJobs"
            >
              重置卡死的运行中任务
            </el-button>
            <div v-if="stuckJobs.length" class="stuck-reset-hint">
              <p class="stuck-reset-count">
                当前 {{ stuckJobs.length }} 条任务卡死（状态为运行中，但无活跃执行）：
              </p>
              <ul class="stuck-reset-list">
                <li v-for="row in stuckJobs" :key="row.job_id">
                  <strong>{{ row.merchant_code || '—' }}</strong>
                  · {{ row.account_name || '—' }}
                  · 卡死阶段：{{ stuckStageSummary(row) || '—' }}
                  · 更新于 {{ row.updated_at || '—' }}
                </li>
              </ul>
            </div>
            <p v-else class="stuck-reset-empty">当前无卡死任务</p>
          </div>
          <el-table
            v-loading="sequentialJobsLoading"
            :data="sequentialJobs"
            stripe
            border
            size="small"
            empty-text="暂无分阶段任务"
          >
            <el-table-column prop="merchant_code" label="商品编码" width="120" show-overflow-tooltip />
            <el-table-column prop="account_name" label="店铺" width="100" show-overflow-tooltip />
            <el-table-column label="上架" width="80">
              <template #default="{ row }: { row: FailureSequentialJob }">
                <el-tag :type="stageStatusType(row.listing_status)" size="small">
                  {{ stageStatusLabel(row.listing_status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="限时" width="90">
              <template #default="{ row }: { row: FailureSequentialJob }">
                <el-tag :type="stageStatusType(row.limited_time_status)" size="small">
                  {{ stageStatusLabel(row.limited_time_status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="618" width="80">
              <template #default="{ row }: { row: FailureSequentialJob }">
                <el-tag :type="stageStatusType(row.activity_618_status)" size="small">
                  {{ stageStatusLabel(row.activity_618_status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="七折" width="80">
              <template #default="{ row }: { row: FailureSequentialJob }">
                <el-tag :type="stageStatusType(row.activity_discount_status)" size="small">
                  {{ stageStatusLabel(row.activity_discount_status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="推广" width="80">
              <template #default="{ row }: { row: FailureSequentialJob }">
                <el-tag :type="stageStatusType(row.promotion_status)" size="small">
                  {{ stageStatusLabel(row.promotion_status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="updated_at" label="更新时间" width="160" />
          </el-table>
        </el-collapse-item>

        <el-collapse-item title="最近拉取记录（调试）" name="poll-logs">
          <el-table
            v-loading="pollLogsLoading"
            :data="pollLogs"
            stripe
            border
            size="small"
            empty-text="暂无拉取记录"
            class="mb-12"
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
          <div v-if="expandedPollId" class="poll-detail">
            <template v-for="log in pollLogs" :key="log.poll_log_id">
              <div v-if="log.poll_log_id === expandedPollId">
                <h4 v-if="log.new_candidates.length">
                  本轮新发现（{{ log.new_candidates.length }}）
                </h4>
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
                  <el-table-column
                    prop="failure_reason"
                    label="失败原因"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <el-table-column
                    prop="source_pipeline_id"
                    label="原链路 ID"
                    width="150"
                    show-overflow-tooltip
                  />
                  <el-table-column label="操作" width="90" fixed="right">
                    <template #default="{ row }: { row: PddFailureCycleRelistPollCandidate }">
                      <el-button
                        link
                        type="primary"
                        :loading="isTriggering(row.record_id)"
                        :disabled="
                          isManualTriggerBlocked(row) ||
                          (!!triggeringRecordId && !isTriggering(row.record_id))
                        "
                        @click="manualTrigger(row)"
                      >
                        手动跑
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <h4>全部候选（{{ log.candidates.length }}）</h4>
                <el-table :data="log.candidates" stripe border size="small">
                  <el-table-column prop="merchant_code" label="商品编码" width="130" />
                  <el-table-column prop="account_name" label="店铺" width="110" />
                  <el-table-column
                    prop="failure_reason"
                    label="失败原因"
                    min-width="180"
                    show-overflow-tooltip
                  />
                  <el-table-column
                    prop="source_pipeline_id"
                    label="原链路 ID"
                    width="150"
                    show-overflow-tooltip
                  />
                </el-table>
              </div>
            </template>
          </div>
        </el-collapse-item>

        <el-collapse-item title="查飞书全平台失败表" name="feishu-table">
          <div class="toolbar mb-12">
            <div class="meta" v-if="data?.ok">
              <span>表：{{ data.table_name || '—' }}</span>
              <span>共 {{ data.total }} 条</span>
            </div>
            <div class="meta" v-else-if="!readFailureTableEnabled">
              <span>表：全平台发布日志表（失败）</span>
              <span class="muted">未读取</span>
            </div>
            <div class="actions">
              <el-switch
                v-model="readFailureTableEnabled"
                inline-prompt
                active-text="读取表"
                inactive-text="不读取"
                @change="onReadFailureTableChange"
              />
              <el-input-number
                v-model="limit"
                :min="1"
                :max="500"
                :step="50"
                :disabled="!readFailureTableEnabled"
              />
              <el-button
                type="primary"
                :loading="loading"
                :disabled="!readFailureTableEnabled"
                @click="load"
              >
                刷新
              </el-button>
            </div>
          </div>

          <el-empty
            v-if="!readFailureTableEnabled"
            description="默认不读飞书全表以减轻噪音。需要时打开「读取表」再刷新。"
            :image-size="64"
          />
          <el-table
            v-else
            v-loading="loading"
            :data="items"
            stripe
            border
            size="small"
            style="width: 100%"
          >
            <el-table-column prop="merchant_code" label="商品编码" width="140" show-overflow-tooltip />
            <el-table-column prop="account_name" label="店铺" width="120" show-overflow-tooltip />
            <el-table-column prop="failure_reason" label="失败原因" min-width="200" show-overflow-tooltip />
            <el-table-column
              prop="source_pipeline_id"
              label="原链路 ID"
              width="150"
              show-overflow-tooltip
            />
            <el-table-column prop="system_reason" label="系统原因" min-width="160" show-overflow-tooltip />
            <el-table-column label="处理状态" width="140">
              <template #default="{ row }">
                <el-tag
                  :type="processTagType(row.process_completed.label, row.process_completed.source)"
                  size="small"
                >
                  {{ row.process_completed.label || '—' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }: { row: PddFailureLogRecord }">
                <el-button
                  link
                  type="primary"
                  :loading="isTriggering(row.record_id)"
                  :disabled="
                    isManualTriggerBlocked(row) ||
                    (!!triggeringRecordId && !isTriggering(row.record_id))
                  "
                  @click="manualTrigger(row)"
                >
                  {{ isManualTriggerBlocked(row) ? '已跑成功' : '手动跑' }}
                </el-button>
                <el-button link type="primary" @click="openDebug(row)">原始数据</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </el-card>

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

.mb-8 {
  margin-bottom: 8px;
}

.section-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.section-title-divider {
  flex: 1;
  margin: 0;
}

.stuck-reset-panel {
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}

.stuck-reset-hint {
  margin-top: 10px;
}

.stuck-reset-count {
  margin: 0 0 8px;
  color: var(--el-color-warning);
  font-size: 13px;
}

.stuck-reset-list {
  margin: 0;
  padding-left: 18px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.7;
}

.stuck-reset-empty {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
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

.meta .muted {
  color: var(--el-text-color-placeholder);
}

.muted {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}

.warn-text {
  color: var(--el-color-warning);
}

.mode-chip {
  color: var(--el-color-success);
  font-weight: 500;
}

.switch-pair {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: center;
}

.rules-compact :deep(.el-form-item) {
  margin-bottom: 14px;
}

.more-settings {
  border: none;
  margin-top: 4px;
}

.more-settings :deep(.el-collapse-item__header) {
  height: 36px;
  line-height: 36px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  border-bottom: none;
}

.primary-work {
  border: 1px solid var(--el-color-primary-light-5);
}

:deep(.row-missing-pipeline) {
  --el-table-tr-bg-color: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
}

.actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.ml-12 {
  margin-left: 12px;
}

.watch-form {
  max-width: 640px;
}

.activity-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.form-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.exclude-reason-editor {
  width: 100%;
}

.exclude-reason-input-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.exclude-reason-input-row .el-input {
  flex: 1;
}

.exclude-reason-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.exclude-reason-tag {
  max-width: 100%;
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
