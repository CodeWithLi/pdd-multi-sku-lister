<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Bell,
  ChatDotRound,
  Clock,
  Document,
  Position,
} from '@element-plus/icons-vue'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import { buildDailyReportMarkdown } from '@/utils/wecomDailyReportMarkdown'
import type {
  WecomConfig,
  WecomDailyReportPlatform,
  WecomDailyReportPreview,
  WecomHealth,
  WecomMsgType,
  WecomTestSendResult,
} from '@/types'

const loading = ref(false)
const saving = ref(false)
const savingDailyContent = ref(false)
const savingPreview = ref(false)
const sending = ref(false)
const triggeringPddReport = ref(false)
const triggeringTaobaoReport = ref(false)
const previewing = ref(false)
const health = ref<WecomHealth | null>(null)
const lastResult = ref<WecomTestSendResult | null>(null)
const scheduleLastRunDate = ref('')
const scheduleRunning = ref(false)
const dailyContentDate = ref('')
const dailyContentUpdatedAt = ref('')
const dailyContentDbAvailable = ref(false)
const pddPreviewSaved = ref(false)
const previewPlatform = ref<WecomDailyReportPlatform>('pdd')
const reportPreview = ref<WecomDailyReportPreview | null>(null)
const sendingPreviewReport = ref(false)

const editableReport = reactive({
  platform: 'pdd' as WecomDailyReportPlatform,
  report_date: '',
  progress_summary: '',
  store_progress: '',
  netdisk_materials: '',
  in_progress: '',
  listing_window_start: '',
  listing_window_end: '',
  git_window_start: '',
  git_window_end: '',
})

const inProgressAutoDraft = ref('')
const progressSummaryFromCache = ref(false)

const webhookMasked = ref('')
const webhookConfigured = ref(false)
const webhookEditing = ref(false)
const webhookDraft = ref('')
const dailyReportWebhookMasked = ref('')
const dailyReportWebhookConfigured = ref(false)
const dailyReportWebhookEditing = ref(false)
const dailyReportWebhookDraft = ref('')

const reportLogs = ref<import('@/types').WecomDailyReportLog[]>([])
const reportLogsTotal = ref(0)
const reportLogsLoading = ref(false)
const reportLogDetail = ref<import('@/types').WecomDailyReportLogDetail | null>(null)
const reportLogDialogVisible = ref(false)

const configForm = reactive({
  enabled: false,
  notify_on_listing_failed: false,
  notify_on_pipeline_failed: false,
  notify_on_commerce_queued: false,
  notify_on_commerce_dispatched: false,
  daily_report_schedule_enabled: false,
  daily_report_schedule_hour: 18,
  daily_report_schedule_minute: 0,
  daily_report_schedule_use_saved_preview: false,
  daily_report_include_activity_promotion: false,
  daily_report_include_limited_time_gap: true,
})

const scheduleTimeDisplay = computed(() => {
  const h = String(configForm.daily_report_schedule_hour).padStart(2, '0')
  const m = String(configForm.daily_report_schedule_minute).padStart(2, '0')
  return `${h}:${m}`
})

const dailyContentForm = reactive({
  pdd_in_progress: '',
  taobao_netdisk_materials: '',
  taobao_in_progress: '',
})

const testForm = reactive({
  msgtype: 'text' as WecomMsgType,
  content: '【拼多多上架助手】企业微信通知测试',
  raw_json: '{\n  "msgtype": "text",\n  "text": {\n    "content": "自定义 JSON 测试"\n  }\n}',
  use_saved_webhook: true,
  override_webhook_url: '',
})

const statusType = computed(() => {
  if (!health.value?.webhook_configured) return 'info'
  if (!health.value?.enabled) return 'warning'
  if (health.value?.configured) return 'success'
  return 'warning'
})

const statusLabel = computed(() => {
  if (!health.value?.webhook_configured) return '未配置 Webhook'
  if (!health.value?.enabled) return '已配置但未启用'
  return '已启用，可发送'
})

function applyConfig(cfg: WecomConfig) {
  configForm.enabled = cfg.enabled
  webhookMasked.value = cfg.webhook_url_masked || ''
  webhookConfigured.value = Boolean(cfg.webhook_configured)
  dailyReportWebhookMasked.value = cfg.webhook_url_daily_report_masked || ''
  dailyReportWebhookConfigured.value = Boolean(cfg.webhook_daily_report_configured)
  configForm.notify_on_listing_failed = cfg.notify_on_listing_failed
  configForm.notify_on_pipeline_failed = cfg.notify_on_pipeline_failed
  configForm.notify_on_commerce_queued = cfg.notify_on_commerce_queued
  configForm.notify_on_commerce_dispatched = cfg.notify_on_commerce_dispatched
  configForm.daily_report_schedule_enabled = cfg.daily_report_schedule_enabled
  configForm.daily_report_schedule_hour = cfg.daily_report_schedule_hour
  configForm.daily_report_schedule_minute = cfg.daily_report_schedule_minute
  configForm.daily_report_schedule_use_saved_preview = cfg.daily_report_schedule_use_saved_preview
  configForm.daily_report_include_activity_promotion = cfg.daily_report_include_activity_promotion
  configForm.daily_report_include_limited_time_gap = cfg.daily_report_include_limited_time_gap
  scheduleLastRunDate.value = cfg.daily_report_last_run_date || ''
  scheduleRunning.value = Boolean(cfg.daily_report_scheduler_running)
  webhookEditing.value = false
  webhookDraft.value = ''
  dailyReportWebhookEditing.value = false
  dailyReportWebhookDraft.value = ''
}

function startWebhookEdit() {
  webhookEditing.value = true
  webhookDraft.value = ''
}

function cancelWebhookEdit() {
  webhookEditing.value = false
  webhookDraft.value = ''
}

function startDailyReportWebhookEdit() {
  dailyReportWebhookEditing.value = true
  dailyReportWebhookDraft.value = ''
}

function cancelDailyReportWebhookEdit() {
  dailyReportWebhookEditing.value = false
  dailyReportWebhookDraft.value = ''
}

function applyDailyContent(data: {
  content_date: string
  pdd_in_progress: string
  pdd_progress_summary?: string
  pdd_store_progress?: string
  pdd_listing_window_start?: string
  pdd_listing_window_end?: string
  pdd_git_window_start?: string
  pdd_git_window_end?: string
  pdd_preview_saved?: boolean
  taobao_netdisk_materials: string
  taobao_in_progress: string
  updated_at?: string
  database_available?: boolean
}) {
  dailyContentForm.pdd_in_progress = data.pdd_in_progress || ''
  dailyContentForm.taobao_netdisk_materials = data.taobao_netdisk_materials || ''
  dailyContentForm.taobao_in_progress = data.taobao_in_progress || ''
  dailyContentDate.value = data.content_date || ''
  dailyContentUpdatedAt.value = data.updated_at || ''
  dailyContentDbAvailable.value = Boolean(data.database_available)
  pddPreviewSaved.value = Boolean(data.pdd_preview_saved)
}

async function loadReportLogs() {
  reportLogsLoading.value = true
  try {
    const data = await api.wecomDailyReportLogs({ page: 1, page_size: 20 })
    reportLogs.value = data.items
    reportLogsTotal.value = data.total
  } catch {
    reportLogs.value = []
    reportLogsTotal.value = 0
  } finally {
    reportLogsLoading.value = false
  }
}

async function openReportLog(logId: string) {
  try {
    reportLogDetail.value = await api.wecomDailyReportLog(logId)
    reportLogDialogVisible.value = true
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载日报记录失败')
  }
}

async function load() {
  loading.value = true
  try {
    const [cfg, h, dailyContent, inProgressDraft] = await Promise.all([
      api.wecomConfig(),
      api.wecomHealth(),
      api.wecomDailyContent(),
      api.wecomInProgressDraft().catch(() => null),
    ])
    health.value = h
    applyConfig(cfg)
    applyDailyContent(dailyContent)
    if (inProgressDraft?.draft) {
      inProgressAutoDraft.value = inProgressDraft.draft
    }
    void loadReportLogs()
    if (dailyContent.pdd_preview_saved) {
      void restoreSavedPreview('pdd', { silent: true })
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载配置失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const webhookUrl = webhookEditing.value ? webhookDraft.value.trim() : ''
    const dailyReportWebhookUrl = dailyReportWebhookEditing.value
      ? dailyReportWebhookDraft.value.trim()
      : ''
    const cfg = await api.updateWecomConfig({
      enabled: configForm.enabled,
      webhook_url: webhookUrl,
      webhook_url_daily_report: dailyReportWebhookUrl,
      notify_on_listing_failed: configForm.notify_on_listing_failed,
      notify_on_pipeline_failed: configForm.notify_on_pipeline_failed,
      notify_on_commerce_queued: configForm.notify_on_commerce_queued,
      notify_on_commerce_dispatched: configForm.notify_on_commerce_dispatched,
      daily_report_schedule_enabled: configForm.daily_report_schedule_enabled,
      daily_report_schedule_hour: configForm.daily_report_schedule_hour,
      daily_report_schedule_minute: configForm.daily_report_schedule_minute,
      daily_report_schedule_use_saved_preview: configForm.daily_report_schedule_use_saved_preview,
      daily_report_include_activity_promotion: configForm.daily_report_include_activity_promotion,
      daily_report_include_limited_time_gap: configForm.daily_report_include_limited_time_gap,
    })
    applyConfig(cfg)
    health.value = await api.wecomHealth()
    ElMessage.success('企业微信配置已保存')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function saveDailyContent(silent = false) {
  savingDailyContent.value = true
  try {
    const data = await api.updateWecomDailyContent({
      pdd_in_progress: dailyContentForm.pdd_in_progress,
      taobao_netdisk_materials: dailyContentForm.taobao_netdisk_materials,
      taobao_in_progress: dailyContentForm.taobao_in_progress,
    })
    applyDailyContent(data)
    if (!silent) {
      ElMessage.success('日报手动内容已保存')
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
    throw e
  } finally {
    savingDailyContent.value = false
  }
}

async function previewDailyReport(platform: WecomDailyReportPlatform) {
  previewing.value = true
  previewPlatform.value = platform
  try {
    await saveDailyContent(true)
    const preview = await api.wecomDailyReportPreview(platform)
    reportPreview.value = preview
    applyPreviewToEditable(preview)
  } catch (e) {
    if (!(e instanceof Error)) {
      ElMessage.error('预览失败')
    }
  } finally {
    previewing.value = false
  }
}

async function restoreSavedPreview(
  platform: WecomDailyReportPlatform = 'pdd',
  options: { silent?: boolean } = {},
) {
  previewing.value = true
  previewPlatform.value = platform
  try {
    const preview = await api.wecomDailyReportPreview(platform)
    reportPreview.value = preview
    applyPreviewToEditable(preview)
    if (!options.silent) {
      ElMessage.success('已加载今日保存的预览，可继续编辑')
    }
  } catch (e) {
    if (!options.silent) {
      ElMessage.error(e instanceof Error ? e.message : '加载已保存预览失败')
    }
  } finally {
    previewing.value = false
  }
}

async function savePreviewEdits() {
  if (!reportPreview.value) {
    ElMessage.warning('请先预览日报')
    return
  }
  if (!dailyContentDbAvailable.value) {
    ElMessage.error('数据库不可用，无法保存预览')
    return
  }
  savingPreview.value = true
  try {
    const data = await api.saveWecomDailyPreview({
      progress_summary: editableReport.progress_summary,
      store_progress: editableReport.store_progress,
      in_progress: editableReport.in_progress,
      listing_window_start: editableReport.listing_window_start,
      listing_window_end: editableReport.listing_window_end,
      git_window_start: editableReport.git_window_start,
      git_window_end: editableReport.git_window_end,
    })
    applyDailyContent(data)
    dailyContentForm.pdd_in_progress = editableReport.in_progress
    reportPreview.value = { ...reportPreview.value, message: liveMarkdown.value }
    ElMessage.success('预览内容已保存，定时发送将使用此版本')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存预览失败')
  } finally {
    savingPreview.value = false
  }
}

async function sendEditedDailyReport() {
  if (!reportPreview.value) {
    ElMessage.warning('请先预览日报')
    return
  }
  sendingPreviewReport.value = true
  try {
    const result = await api.wecomDailyReportTrigger({
      platform: editableReport.platform,
      message: liveMarkdown.value,
    })
    if (result.ok) {
      ElMessage.success(result.message || '日报已发送')
      reportPreview.value = { ...reportPreview.value, message: liveMarkdown.value }
      if (editableReport.platform === 'pdd') {
        const cfg = await api.wecomConfig()
        applyConfig(cfg)
      }
      void loadReportLogs()
    } else {
      ElMessage.error(result.message || '发送失败')
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '发送失败')
  } finally {
    sendingPreviewReport.value = false
  }
}

async function regenerateDailyReport() {
  if (!reportPreview.value) {
    ElMessage.warning('请先预览日报')
    return
  }
  previewing.value = true
  previewPlatform.value = reportPreview.value.platform
  try {
    await saveDailyContent(true)
    const preview = await api.wecomDailyReportPreview(reportPreview.value.platform, {
      use_saved_preview: false,
    })
    reportPreview.value = preview
    applyPreviewToEditable(preview)
    ElMessage.success('已根据最新数据重新生成，未覆盖已保存预览')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '重新生成失败')
  } finally {
    previewing.value = false
  }
}

async function resetPreviewEdits() {
  if (!reportPreview.value) return
  applyPreviewToEditable(reportPreview.value)
  ElMessage.info('已恢复为当前预览内容')
}

function splitReportLines(text: string) {
  return String(text || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

async function triggerDailyReport(platform: WecomDailyReportPlatform) {
  const loadingRef = platform === 'pdd' ? triggeringPddReport : triggeringTaobaoReport
  loadingRef.value = true
  try {
    await saveDailyContent(true)
    let message = ''
    if (reportPreview.value?.platform === platform) {
      message = liveMarkdown.value
    } else {
      const preview = await api.wecomDailyReportPreview(platform)
      reportPreview.value = preview
      applyPreviewToEditable(preview)
      message = liveMarkdown.value
    }
    const result = await api.wecomDailyReportTrigger({ platform, message })
    if (result.ok) {
      ElMessage.success(result.message || '日报已发送')
      if (platform === 'pdd') {
        const cfg = await api.wecomConfig()
        applyConfig(cfg)
      }
      void loadReportLogs()
    } else {
      ElMessage.error(result.message || '发送失败')
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '发送失败')
  } finally {
    loadingRef.value = false
  }
}

async function sendTest() {
  sending.value = true
  lastResult.value = null
  try {
    const payload: Parameters<typeof api.wecomTestSend>[0] = {
      msgtype: testForm.msgtype,
      content: testForm.content,
      use_saved_webhook: testForm.use_saved_webhook,
    }

    if (testForm.msgtype === 'raw') {
      try {
        payload.raw_payload = JSON.parse(testForm.raw_json)
      } catch {
        ElMessage.error('raw JSON 格式不正确')
        return
      }
    }

    if (!testForm.use_saved_webhook) {
      payload.webhook_url = testForm.override_webhook_url.trim()
    }

    const result = await api.wecomTestSend(payload)
    lastResult.value = result
    if (result.ok) {
      ElMessage.success('测试消息已发送，请到企业微信群查看')
    } else {
      ElMessage.error(result.errmsg || '发送失败')
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '发送失败')
  } finally {
    sending.value = false
  }
}

function fillMarkdownSample() {
  testForm.msgtype = 'markdown'
  testForm.content = [
    '## 整合链路通知测试',
    '> 店铺：<font color="info">兔兔潮玩屋</font>',
    '> 状态：<font color="warning">上架失败</font>',
    '',
    '请登录系统查看详情。',
  ].join('\n')
}

function fillMarkdownV2Sample() {
  testForm.msgtype = 'markdown_v2'
  testForm.content = '**整合链路通知测试**\n店铺：兔兔潮玩屋\n状态：上架失败'
}

const contentTab = ref<'pdd' | 'taobao'>('pdd')

const notifyOptions = [
  { key: 'notify_on_listing_failed', label: '上架失败', desc: '单条上架失败时推送', tone: 'danger' },
  { key: 'notify_on_pipeline_failed', label: '链路失败', desc: '整合链路异常时推送', tone: 'warning' },
  { key: 'notify_on_commerce_queued', label: '任务排队', desc: '运营任务进入排队时推送', tone: 'info' },
  { key: 'notify_on_commerce_dispatched', label: '任务派发', desc: '排队任务正式派发时推送', tone: 'success' },
] as const

function applyPreviewToEditable(preview: WecomDailyReportPreview) {
  editableReport.platform = preview.platform
  editableReport.report_date = preview.report_date
  editableReport.progress_summary = preview.progress_summary || ''
  editableReport.store_progress = preview.store_progress || ''
  editableReport.netdisk_materials = preview.netdisk_materials || ''
  editableReport.in_progress = preview.in_progress || ''
  editableReport.listing_window_start = preview.listing_window_start || ''
  editableReport.listing_window_end = preview.listing_window_end || ''
  editableReport.git_window_start = preview.git_window_start || preview.listing_window_start || ''
  editableReport.git_window_end = preview.git_window_end || preview.listing_window_end || ''
  inProgressAutoDraft.value = preview.in_progress_auto_draft || ''
  progressSummaryFromCache.value = Boolean(preview.progress_summary_from_cache)
}

function fillInProgressSuggestion() {
  const draft = String(inProgressAutoDraft.value || '').trim()
  if (!draft) {
    ElMessage.info('当前没有系统建议条目')
    return
  }
  const current = String(dailyContentForm.pdd_in_progress || '').trim()
  if (!current) {
    dailyContentForm.pdd_in_progress = draft
    editableReport.in_progress = draft
    ElMessage.success('已填入系统建议')
    return
  }
  const seen = new Set(
    current
      .split('\n')
      .map((line) => line.trim().toLowerCase())
      .filter(Boolean),
  )
  const extras = draft
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line && !seen.has(line.toLowerCase()))
  if (!extras.length) {
    ElMessage.info('手动内容已覆盖全部建议')
    return
  }
  dailyContentForm.pdd_in_progress = `${current}\n${extras.join('\n')}`
  editableReport.in_progress = dailyContentForm.pdd_in_progress
  ElMessage.success('已追加未重复的系统建议')
}

const liveMarkdown = computed(() =>
  buildDailyReportMarkdown({
    platform: editableReport.platform,
    reportDate: editableReport.report_date,
    progressSummary: editableReport.progress_summary,
    storeProgress: editableReport.store_progress,
    netdiskMaterials: editableReport.netdisk_materials,
    inProgress: editableReport.in_progress,
    listingWindowStart: editableReport.listing_window_start,
    listingWindowEnd: editableReport.listing_window_end,
    gitWindowStart: editableReport.git_window_start,
    gitWindowEnd: editableReport.git_window_end,
  }),
)

const previewDirty = computed(() => {
  if (!reportPreview.value) return false
  return liveMarkdown.value !== reportPreview.value.message
})

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="wecom-page" v-loading="loading">
    <PageHeader
      title="企业微信通知"
      desc="Webhook 连接、业务告警、运营日报一站式配置"
    />

    <section class="status-hero" :class="`is-${statusType}`">
      <div class="status-hero-main">
        <div class="status-icon-wrap">
          <el-icon class="status-icon"><ChatDotRound /></el-icon>
        </div>
        <div>
          <div class="status-title">{{ statusLabel }}</div>
          <div v-if="health" class="status-sub">
            <code>{{ health.config_path || '—' }}</code>
            <span v-if="health.webhook_configured && !health.enabled">保存并启用后即可推送</span>
          </div>
        </div>
      </div>
      <div class="status-hero-tags">
        <span v-if="scheduleRunning" class="status-chip is-green">调度运行中</span>
        <span v-if="dailyContentDbAvailable" class="status-chip is-blue">日报 MySQL</span>
        <span v-else class="status-chip is-amber">数据库未就绪</span>
      </div>
    </section>

    <div class="wecom-grid">
      <section class="panel panel-connection accent-wecom">
        <header class="panel-header">
          <div class="panel-heading">
            <div class="panel-icon wecom"><el-icon><ChatDotRound /></el-icon></div>
            <div>
              <div class="panel-title">连接与告警</div>
              <div class="panel-desc">Webhook 与业务异常自动通知</div>
            </div>
          </div>
          <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
        </header>

        <div class="panel-body">
          <div class="setting-row highlight">
            <div class="setting-label">
              <span>启用企业微信通知</span>
              <small>关闭后所有推送暂停</small>
            </div>
            <el-switch v-model="configForm.enabled" />
          </div>

          <div class="field-block">
            <label class="field-label">告警 Webhook 地址</label>
            <template v-if="!webhookEditing">
              <div class="webhook-row">
                <el-input
                  :model-value="webhookConfigured ? webhookMasked : ''"
                  readonly
                  placeholder="尚未配置 Webhook"
                />
                <el-button @click="startWebhookEdit">{{ webhookConfigured ? '更换' : '填写' }}</el-button>
              </div>
              <p class="field-hint">用于上架失败、链路失败等业务告警；地址脱敏显示。</p>
            </template>
            <template v-else>
              <el-input
                v-model="webhookDraft"
                type="textarea"
                :rows="3"
                placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
              />
              <el-button link type="primary" @click="cancelWebhookEdit">取消更换</el-button>
            </template>
          </div>

          <div class="subsection">
            <div class="subsection-title">自动通知</div>
            <div class="switch-grid">
              <div
                v-for="item in notifyOptions"
                :key="item.key"
                class="switch-card"
                :class="`tone-${item.tone}`"
              >
                <div class="switch-card-text">
                  <strong>{{ item.label }}</strong>
                  <span>{{ item.desc }}</span>
                </div>
                <el-switch v-model="configForm[item.key]" />
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="panel panel-daily accent-brand">
        <header class="panel-header">
          <div class="panel-heading">
            <div class="panel-icon brand"><el-icon><Document /></el-icon></div>
            <div>
              <div class="panel-title">日报内容</div>
              <div class="panel-desc">
                按自然日保存
                <template v-if="dailyContentDate"> · {{ dailyContentDate }}</template>
                <template v-if="dailyContentUpdatedAt"> · 已保存 {{ dailyContentUpdatedAt }}</template>
              </div>
            </div>
          </div>
          <el-button type="primary" plain :loading="savingDailyContent" @click="saveDailyContent()">
            保存内容
          </el-button>
        </header>

        <div class="panel-body">
          <el-alert
            v-if="!dailyContentDbAvailable"
            type="warning"
            :closable="false"
            show-icon
            title="数据库不可用，无法保存日报手动内容"
            class="inline-alert"
          />

          <div class="platform-pills">
            <button
              type="button"
              class="platform-pill"
              :class="{ active: contentTab === 'pdd' }"
              @click="contentTab = 'pdd'"
            >
              PDD 日报
            </button>
            <button
              type="button"
              class="platform-pill"
              :class="{ active: contentTab === 'taobao' }"
              @click="contentTab = 'taobao'"
            >
              淘宝日报
            </button>
          </div>

          <div v-show="contentTab === 'pdd'" class="platform-pane">
            <div class="platform-note">
              技术进展与店铺数据自动生成（统计窗口：昨天 18:01 ~ 今天 18:00）。
              「正在解决/优化中」可手填，预览时会自动合并当日链路报错建议。
              每日仅保留一份已保存预览，多次点「保存预览」以最后一次为准；刷新后会自动恢复今日已保存预览。
            </div>
            <el-alert
              v-if="pddPreviewSaved && !reportPreview"
              type="info"
              :closable="false"
              show-icon
              class="inline-alert preview-restore-alert"
            >
              <template #title>
                今日预览已保存
                <template v-if="dailyContentUpdatedAt">（{{ dailyContentUpdatedAt }}）</template>
              </template>
              <el-button
                size="small"
                type="primary"
                plain
                :loading="previewing"
                @click="restoreSavedPreview('pdd')"
              >
                打开已保存预览
              </el-button>
            </el-alert>
            <div v-if="inProgressAutoDraft" class="auto-draft-box">
              <div class="auto-draft-head">
                <span class="field-label">系统建议（未保存）</span>
                <el-button link type="primary" @click="fillInProgressSuggestion">填入编辑框</el-button>
              </div>
              <pre class="auto-draft-text">{{ inProgressAutoDraft }}</pre>
            </div>
            <el-input
              v-model="dailyContentForm.pdd_in_progress"
              type="textarea"
              :rows="8"
              placeholder="例如：修复上架超时问题"
              class="content-textarea"
            />
          </div>

          <div v-show="contentTab === 'taobao'" class="platform-pane">
            <div class="platform-note">淘宝日报全部手动填写，发送前请先保存。</div>
            <label class="field-label">网盘素材和上架累计数据</label>
            <el-input
              v-model="dailyContentForm.taobao_netdisk_materials"
              type="textarea"
              :rows="5"
              placeholder="填写今日网盘素材和上架累计数据"
              class="content-textarea"
            />
            <label class="field-label spaced">正在解决 / 优化中</label>
            <el-input
              v-model="dailyContentForm.taobao_in_progress"
              type="textarea"
              :rows="4"
              placeholder="填写淘宝侧正在处理的事项"
              class="content-textarea"
            />
          </div>

          <div class="action-row">
            <div class="action-group">
              <span class="action-label">预览</span>
              <el-button size="small" :loading="previewing && previewPlatform === 'pdd'" @click="previewDailyReport('pdd')">
                PDD
              </el-button>
              <el-button size="small" :loading="previewing && previewPlatform === 'taobao'" @click="previewDailyReport('taobao')">
                淘宝
              </el-button>
            </div>
            <div class="action-divider" />
            <div class="action-group">
              <span class="action-label">发送</span>
              <el-button size="small" type="warning" plain :loading="triggeringPddReport" @click="triggerDailyReport('pdd')">
                PDD
              </el-button>
              <el-button size="small" type="success" plain :loading="triggeringTaobaoReport" @click="triggerDailyReport('taobao')">
                淘宝
              </el-button>
            </div>
          </div>
        </div>
      </section>

      <section class="panel panel-schedule accent-slate">
        <header class="panel-header">
          <div class="panel-heading">
            <div class="panel-icon slate"><el-icon><Clock /></el-icon></div>
            <div>
              <div class="panel-title">PDD 定时日报</div>
              <div class="panel-desc">每天自动发送 PDD 日报（淘宝需手动）</div>
            </div>
          </div>
        </header>

        <div class="panel-body">
          <div class="setting-row">
            <div class="setting-label">
              <span>启用定时发送</span>
              <small>需已配置日报 Webhook 并启用通知</small>
            </div>
            <el-switch v-model="configForm.daily_report_schedule_enabled" />
          </div>

          <div class="setting-row">
            <div class="setting-label">
              <span>定时发送已保存预览</span>
              <small>开启后，到点发送「日报预览」中已保存的内容；未保存则回退实时生成</small>
            </div>
            <el-switch
              v-model="configForm.daily_report_schedule_use_saved_preview"
              :disabled="!configForm.daily_report_schedule_enabled"
            />
          </div>

          <div class="setting-row">
            <div class="setting-label">
              <span>统计活动与推广</span>
              <small>开启后店铺行追加 618大促 / 7折 / 推广成功数；关闭则保持「已发布 + 限时限量购」</small>
            </div>
            <el-switch v-model="configForm.daily_report_include_activity_promotion" />
          </div>

          <div class="setting-row">
            <div class="setting-label">
              <span>限时限量购缺口明细</span>
              <small>开启后，当已发布与限时限量购不匹配时，追加失败原因与未跑数量</small>
            </div>
            <el-switch v-model="configForm.daily_report_include_limited_time_gap" />
          </div>

          <div class="field-block">
            <label class="field-label">日报 Webhook 地址</label>
            <template v-if="!dailyReportWebhookEditing">
              <div class="webhook-row">
                <el-input
                  :model-value="dailyReportWebhookConfigured ? dailyReportWebhookMasked : (webhookConfigured ? '（回退使用告警 Webhook）' : '')"
                  readonly
                  placeholder="未单独配置，将使用告警 Webhook"
                />
                <el-button @click="startDailyReportWebhookEdit">配置</el-button>
              </div>
              <p class="field-hint">日报与业务告警可分到不同群；留空则回退告警 Webhook。修改后请在「连接与告警」保存配置。</p>
            </template>
            <template v-else>
              <el-input
                v-model="dailyReportWebhookDraft"
                type="textarea"
                :rows="3"
                placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
              />
              <el-button link type="primary" @click="cancelDailyReportWebhookEdit">取消</el-button>
            </template>
          </div>

          <div class="time-panel">
            <div class="time-panel-label">每天发送时间</div>
            <div class="time-row">
              <el-input-number v-model="configForm.daily_report_schedule_hour" :min="0" :max="23" controls-position="right" />
              <span>时</span>
              <el-input-number v-model="configForm.daily_report_schedule_minute" :min="0" :max="59" controls-position="right" />
              <span>分</span>
            </div>
            <div class="time-badge">{{ scheduleTimeDisplay }} · Asia/Shanghai</div>
            <p class="field-hint">店铺统计窗口：昨天 18:01 ~ 今天 18:00</p>
          </div>

          <div class="schedule-meta-box">
            <span>{{ scheduleLastRunDate ? `上次自动发送：${scheduleLastRunDate}` : '今天尚未自动发送' }}</span>
            <span v-if="configForm.daily_report_schedule_use_saved_preview">
              {{ pddPreviewSaved ? ' · 今日预览已保存' : ' · 今日预览未保存' }}
            </span>
          </div>
        </div>
      </section>

      <section class="panel panel-history accent-slate" v-loading="reportLogsLoading">
        <header class="panel-header">
          <div class="panel-heading">
            <div class="panel-icon slate"><el-icon><Document /></el-icon></div>
            <div>
              <div class="panel-title">日报发送历史</div>
              <div class="panel-desc">查看最近发送记录与正文（已发送版本，非编辑草稿）</div>
            </div>
          </div>
          <el-button size="small" @click="loadReportLogs">刷新</el-button>
        </header>
        <div class="panel-body">
          <el-table v-if="reportLogs.length" :data="reportLogs" size="small" stripe>
            <el-table-column prop="created_at" label="发送时间" width="160" />
            <el-table-column prop="platform" label="平台" width="72" />
            <el-table-column prop="report_date" label="报告日" width="110" />
            <el-table-column prop="trigger_kind" label="触发" width="88">
              <template #default="{ row }">
                {{ row.trigger_kind === 'scheduled' ? '定时' : '手动' }}
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">
                  {{ row.status === 'success' ? '成功' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="message_preview" label="摘要" min-width="220" show-overflow-tooltip />
            <el-table-column label="操作" width="88" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openReportLog(row.log_id)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无发送记录" />
          <div v-if="reportLogsTotal > reportLogs.length" class="field-hint">
            共 {{ reportLogsTotal }} 条，仅显示最近 20 条
          </div>
        </div>
      </section>

      <section class="panel panel-test accent-slate">
        <header class="panel-header">
          <div class="panel-heading">
            <div class="panel-icon slate"><el-icon><Position /></el-icon></div>
            <div>
              <div class="panel-title">消息测试</div>
              <div class="panel-desc">验证 Webhook 是否可用</div>
            </div>
          </div>
          <el-button type="success" :loading="sending" @click="sendTest">发送测试</el-button>
        </header>

        <div class="panel-body">
          <el-radio-group v-model="testForm.msgtype" size="small" class="msgtype-group">
            <el-radio-button value="text">文本</el-radio-button>
            <el-radio-button value="markdown">Markdown</el-radio-button>
            <el-radio-button value="markdown_v2">MD v2</el-radio-button>
            <el-radio-button value="raw">JSON</el-radio-button>
          </el-radio-group>

          <el-input
            v-if="testForm.msgtype !== 'raw'"
            v-model="testForm.content"
            type="textarea"
            :rows="5"
            class="content-textarea"
          />
          <el-input v-else v-model="testForm.raw_json" type="textarea" :rows="8" class="content-textarea mono" />

          <div class="sample-actions">
            <el-button link type="primary" @click="fillMarkdownSample">Markdown 样例</el-button>
            <el-button link type="primary" @click="fillMarkdownV2Sample">MD v2 样例</el-button>
          </div>

          <div class="setting-row compact">
            <span class="field-label">使用已保存 Webhook</span>
            <el-switch v-model="testForm.use_saved_webhook" />
          </div>
          <el-input
            v-if="!testForm.use_saved_webhook"
            v-model="testForm.override_webhook_url"
            placeholder="临时 Webhook，仅本次测试"
          />
        </div>
      </section>
    </div>

    <section v-if="reportPreview" class="panel panel-preview accent-wecom" v-loading="previewing">
      <header class="panel-header">
        <div class="panel-heading">
          <div class="panel-icon wecom"><el-icon><Document /></el-icon></div>
          <div>
            <div class="panel-title">
              日报预览与编辑
              <span v-if="pddPreviewSaved" class="saved-badge">已保存</span>
              <span v-if="previewDirty" class="dirty-badge">已修改</span>
            </div>
            <div class="panel-desc">
              {{ editableReport.platform === 'pdd' ? 'PDD' : '淘宝' }} · {{ editableReport.report_date }}
              · 修改后右侧实时更新；手动发送推送当前预览，定时发送需先「保存预览」
            </div>
          </div>
        </div>
        <div class="preview-header-actions">
          <el-button :loading="previewing" @click="regenerateDailyReport">重新生成</el-button>
          <el-button @click="resetPreviewEdits">恢复预览内容</el-button>
          <el-button :loading="savingPreview" @click="savePreviewEdits">保存预览</el-button>
          <el-button
            type="primary"
            :loading="sendingPreviewReport"
            @click="sendEditedDailyReport"
          >
            发送此内容
          </el-button>
        </div>
      </header>

      <div class="preview-editor-layout">
        <div class="preview-editor">
          <template v-if="editableReport.platform === 'pdd'">
            <div class="editor-block">
              <label class="editor-label">
                技术项目进展
                <span v-if="progressSummaryFromCache" class="cache-badge">已缓存</span>
              </label>
              <p class="editor-hint">
                Git 统计窗口：{{ editableReport.git_window_start || '—' }}
                ~ {{ editableReport.git_window_end || '—' }}
              </p>
              <el-input
                v-model="editableReport.progress_summary"
                type="textarea"
                :rows="7"
                placeholder="每行一条，对应「当日已完成交付技术项目进展」"
                class="content-textarea"
              />
            </div>
            <div class="editor-block">
              <label class="editor-label">店铺发布进度</label>
              <p class="editor-hint">
                统计窗口：{{ editableReport.listing_window_start || '—' }}
                ~ {{ editableReport.listing_window_end || '—' }}
              </p>
              <el-input
                v-model="editableReport.store_progress"
                type="textarea"
                :rows="5"
                placeholder="每行一条，例如：店铺名：已发布8个"
                class="content-textarea"
              />
            </div>
            <div class="editor-block">
              <label class="editor-label">正在解决 / 优化中</label>
              <p v-if="inProgressAutoDraft" class="editor-hint">
                含系统建议；保存手动区后预览会合并去重。
              </p>
              <el-input
                v-model="editableReport.in_progress"
                type="textarea"
                :rows="4"
                placeholder="每行一条"
                class="content-textarea"
              />
            </div>
          </template>

          <template v-else>
            <div class="editor-block">
              <label class="editor-label">网盘素材和上架累计数据</label>
              <el-input
                v-model="editableReport.netdisk_materials"
                type="textarea"
                :rows="6"
                placeholder="每行一条"
                class="content-textarea"
              />
            </div>
            <div class="editor-block">
              <label class="editor-label">正在解决 / 优化中</label>
              <el-input
                v-model="editableReport.in_progress"
                type="textarea"
                :rows="4"
                placeholder="每行一条"
                class="content-textarea"
              />
            </div>
          </template>

          <details class="report-raw editor-raw">
            <summary>Markdown 原文（随编辑实时更新）</summary>
            <pre>{{ liveMarkdown }}</pre>
          </details>
        </div>

        <div class="preview-live">
          <div class="preview-live-label">实时预览</div>
          <div class="preview-shell preview-shell-inline">
            <div class="wechat-frame">
              <div class="wechat-topbar">
                <span class="wechat-topbar-title">日报群</span>
                <span class="wechat-topbar-sub">企业微信 · 机器人</span>
              </div>
              <div class="chat-bubble">
                <div class="chat-avatar"><el-icon><Bell /></el-icon></div>
                <div class="chat-body">
                  <div class="chat-bubble-head">
                    <span class="chat-app">拼多多上架助手</span>
                    <span class="chat-time">{{ editableReport.report_date }}</span>
                  </div>
                  <div class="chat-title">日报 · {{ editableReport.platform === 'pdd' ? 'PDD' : '淘宝' }}</div>

                  <template v-if="editableReport.platform === 'pdd'">
                    <div class="chat-section">
                      <div class="chat-section-title">技术项目进展</div>
                      <ul v-if="splitReportLines(editableReport.progress_summary).length" class="chat-list">
                        <li v-for="line in splitReportLines(editableReport.progress_summary)" :key="line">{{ line }}</li>
                      </ul>
                      <div v-else class="chat-empty">今日暂无代码提交</div>
                    </div>
                    <div class="chat-section">
                      <div class="chat-section-title">店铺发布进度</div>
                      <div v-if="editableReport.listing_window_start" class="chat-meta">
                        {{ editableReport.listing_window_start }} ~ {{ editableReport.listing_window_end }}
                      </div>
                      <ul v-if="splitReportLines(editableReport.store_progress).length" class="chat-list">
                        <li v-for="line in splitReportLines(editableReport.store_progress)" :key="line">{{ line }}</li>
                      </ul>
                      <div v-else class="chat-empty">暂无发布记录</div>
                    </div>
                    <div class="chat-section">
                      <div class="chat-section-title">正在解决 / 优化中</div>
                      <ul v-if="splitReportLines(editableReport.in_progress).length" class="chat-list">
                        <li v-for="line in splitReportLines(editableReport.in_progress)" :key="line">{{ line }}</li>
                      </ul>
                      <div v-else class="chat-empty">暂无</div>
                    </div>
                  </template>

                  <template v-else>
                    <div class="chat-section">
                      <div class="chat-section-title">网盘素材和上架累计数据</div>
                      <ul v-if="splitReportLines(editableReport.netdisk_materials).length" class="chat-list">
                        <li v-for="line in splitReportLines(editableReport.netdisk_materials)" :key="line">{{ line }}</li>
                      </ul>
                      <div v-else class="chat-empty">暂无</div>
                    </div>
                    <div class="chat-section">
                      <div class="chat-section-title">正在解决 / 优化中</div>
                      <ul v-if="splitReportLines(editableReport.in_progress).length" class="chat-list">
                        <li v-for="line in splitReportLines(editableReport.in_progress)" :key="line">{{ line }}</li>
                      </ul>
                      <div v-else class="chat-empty">暂无</div>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section v-if="lastResult" class="panel panel-result">
      <header class="panel-header">
        <div class="panel-title">最近测试结果</div>
        <el-tag :type="lastResult.ok ? 'success' : 'danger'" round>{{ lastResult.ok ? '成功' : '失败' }}</el-tag>
      </header>
      <div class="panel-body result-body">
        <div class="result-line"><span>errcode</span><code>{{ lastResult.errcode }}</code></div>
        <div class="result-line"><span>errmsg</span><code>{{ lastResult.errmsg || '—' }}</code></div>
        <details class="report-raw">
          <summary>请求 / 响应详情</summary>
          <pre>{{ JSON.stringify({ payload: lastResult.payload_sent, response: lastResult.response }, null, 2) }}</pre>
        </details>
      </div>
    </section>
  </div>

  <el-dialog
    v-model="reportLogDialogVisible"
    title="日报发送详情"
    width="720px"
    destroy-on-close
  >
    <template v-if="reportLogDetail">
      <div class="log-meta">
        <span>{{ reportLogDetail.created_at }}</span>
        <span>{{ reportLogDetail.platform === 'pdd' ? 'PDD' : '淘宝' }}</span>
        <span>{{ reportLogDetail.trigger_kind === 'scheduled' ? '定时' : '手动' }}</span>
        <el-tag :type="reportLogDetail.status === 'success' ? 'success' : 'danger'" size="small">
          {{ reportLogDetail.status === 'success' ? '成功' : '失败' }}
        </el-tag>
      </div>
      <p v-if="reportLogDetail.window_start" class="field-hint">
        统计窗口：{{ reportLogDetail.window_start }} ~ {{ reportLogDetail.window_end }}
      </p>
      <p v-if="reportLogDetail.errmsg" class="field-hint error-text">{{ reportLogDetail.errmsg }}</p>
      <pre class="log-message">{{ reportLogDetail.message }}</pre>
    </template>
  </el-dialog>
</template>

<style scoped>
.wecom-page {
  display: flex;
  flex-direction: column;
  gap: 22px;
  padding-bottom: 28px;
}

/* ── Status hero ── */
.status-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 20px 24px;
  border-radius: 18px;
  border: 1px solid var(--border-color);
  background: #fff;
  box-shadow: var(--card-shadow);
}

.status-hero.is-success {
  background: linear-gradient(135deg, #f0fdf4 0%, #fff 55%);
  border-color: #bbf7d0;
}

.status-hero.is-warning {
  background: linear-gradient(135deg, #fffbeb 0%, #fff 55%);
  border-color: #fde68a;
}

.status-hero.is-info {
  background: linear-gradient(135deg, #eff6ff 0%, #fff 55%);
  border-color: #bfdbfe;
}

.status-hero-main {
  display: flex;
  align-items: center;
  gap: 16px;
}

.status-icon-wrap {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #07c160, #06ae56);
  color: #fff;
  box-shadow: 0 6px 16px rgba(7, 193, 96, 0.28);
  flex-shrink: 0;
}

.is-warning .status-icon-wrap {
  background: linear-gradient(135deg, #f59e0b, #d97706);
  box-shadow: 0 6px 16px rgba(245, 158, 11, 0.25);
}

.is-info .status-icon-wrap {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  box-shadow: 0 6px 16px rgba(59, 130, 246, 0.25);
}

.status-icon {
  font-size: 24px;
}

.status-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.01em;
}

.status-sub {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.status-sub code {
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.05);
  font-size: 11px;
  color: #475569;
}

.status-hero-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.status-chip {
  padding: 5px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid transparent;
}

.status-chip.is-green {
  background: #ecfdf5;
  color: #047857;
  border-color: #a7f3d0;
}

.status-chip.is-blue {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #bfdbfe;
}

.status-chip.is-amber {
  background: #fffbeb;
  color: #b45309;
  border-color: #fde68a;
}

/* ── Grid layout ── */
.wecom-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr);
  gap: 18px;
}

.panel {
  position: relative;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: var(--card-shadow);
  overflow: hidden;
}

.panel::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: #e2e8f0;
}

.accent-wecom::before { background: linear-gradient(90deg, #07c160, #34d399); }
.accent-brand::before { background: linear-gradient(90deg, var(--brand), #ff8f5a); }
.accent-slate::before { background: linear-gradient(90deg, #64748b, #94a3b8); }

.panel-connection { grid-column: 1; }
.panel-daily { grid-column: 2; grid-row: span 2; }
.panel-schedule { grid-column: 1; }
.panel-test { grid-column: 1; }
.panel-preview,
.panel-result { grid-column: 1 / -1; }

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid #f1f5f9;
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.panel-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.panel-icon.wecom {
  background: #ecfdf5;
  color: #059669;
}

.panel-icon.brand {
  background: var(--brand-light);
  color: var(--brand);
}

.panel-icon.slate {
  background: #f1f5f9;
  color: #475569;
}

.panel-title {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.panel-desc {
  margin-top: 3px;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.45;
}

.panel-body {
  padding: 16px 20px 20px;
}

/* ── Form elements ── */
.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #eef2f7;
}

.setting-row.highlight {
  background: linear-gradient(135deg, #ecfdf5 0%, #f8fafc 100%);
  border-color: #d1fae5;
}

.setting-row.compact {
  margin-top: 12px;
  padding: 10px 12px;
}

.setting-label {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.setting-label span {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
}

.setting-label small,
.field-hint {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}

.field-block { margin-top: 16px; }

.field-label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.field-label.spaced { margin-top: 14px; }

.webhook-row {
  display: flex;
  gap: 10px;
}

.webhook-row .el-input { flex: 1; }

.subsection { margin-top: 18px; }

.subsection-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.subsection-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: #e8edf3;
}

/* ── Switch cards ── */
.switch-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.switch-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #e8edf3;
  border-left-width: 3px;
  transition: box-shadow 0.2s, transform 0.15s;
}

.switch-card:hover {
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
  transform: translateY(-1px);
}

.switch-card.tone-danger { border-left-color: #ef4444; }
.switch-card.tone-warning { border-left-color: #f59e0b; }
.switch-card.tone-info { border-left-color: #3b82f6; }
.switch-card.tone-success { border-left-color: #22c55e; }

.switch-card-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.switch-card-text strong {
  font-size: 13px;
  color: #1e293b;
}

.switch-card-text span {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
}

/* ── Platform tabs ── */
.platform-pills {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  margin-bottom: 14px;
  border-radius: 12px;
  background: #f1f5f9;
}

.platform-pill {
  border: none;
  background: transparent;
  padding: 8px 18px;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.18s;
}

.platform-pill:hover {
  color: #334155;
}

.platform-pill.active {
  background: #fff;
  color: var(--brand);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
}

.platform-pane {
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.platform-note {
  margin-bottom: 12px;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--brand-light);
  border: 1px solid #ffe0d0;
  font-size: 12px;
  color: #9a3412;
  line-height: 1.6;
}

.auto-draft-box {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
}

.auto-draft-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.auto-draft-text {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
  white-space: pre-wrap;
}

.cache-badge {
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #ecfdf5;
  color: #047857;
  font-size: 11px;
  font-weight: 500;
}

.log-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #475569;
}

.log-message {
  margin: 0;
  padding: 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.6;
  max-height: 420px;
  overflow: auto;
}

.error-text {
  color: #b91c1c;
}

.content-textarea :deep(textarea) {
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.65;
  border-color: #e2e8f0;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.content-textarea :deep(textarea:focus) {
  border-color: #ffd4c2;
  box-shadow: 0 0 0 3px rgba(255, 107, 53, 0.1);
}

.mono :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

/* ── Action row ── */
.action-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid #f1f5f9;
}

.action-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.action-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-right: 2px;
}

.action-divider {
  width: 1px;
  height: 24px;
  background: #e2e8f0;
}

/* ── Schedule ── */
.time-panel {
  margin-top: 14px;
  padding: 16px;
  border-radius: 14px;
  background: linear-gradient(180deg, #f8fafc 0%, #fff 100%);
  border: 1px solid #e8edf3;
}

.time-panel-label {
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.time-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.time-badge {
  display: inline-block;
  margin-top: 10px;
  padding: 4px 12px;
  border-radius: 999px;
  background: #fff4ef;
  color: #c2410c;
  border: 1px solid #ffd4c2;
  font-size: 12px;
  font-weight: 600;
}

.schedule-meta-box {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 10px;
  background: #f8fafc;
  font-size: 12px;
  color: var(--text-secondary);
}

.msgtype-group { margin-bottom: 12px; }

.sample-actions {
  display: flex;
  gap: 12px;
  margin-top: 8px;
}

.inline-alert { margin-bottom: 12px; }

/* ── Preview editor layout ── */
.preview-header-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.dirty-badge {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #fff7ed;
  color: #c2410c;
  border: 1px solid #fed7aa;
  font-size: 11px;
  font-weight: 600;
  vertical-align: middle;
}

.saved-badge {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
  font-size: 11px;
  font-weight: 600;
  vertical-align: middle;
}

.preview-restore-alert :deep(.el-alert__content) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.preview-editor-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0;
  min-height: 420px;
}

.preview-editor {
  padding: 18px 20px;
  border-right: 1px solid #f1f5f9;
  overflow-y: auto;
}

.preview-live {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.preview-live-label {
  padding: 12px 20px 0;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.editor-block + .editor-block {
  margin-top: 16px;
}

.editor-label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 700;
  color: #334155;
}

.editor-hint {
  margin: 0 0 8px;
  font-size: 11px;
  color: var(--text-muted);
}

.editor-raw {
  margin-top: 16px;
}

.editor-raw pre {
  max-height: 200px;
}

.preview-shell-inline {
  flex: 1;
  padding: 12px 16px 20px;
}

/* ── Preview (WeChat style) ── */
.preview-shell {
  padding: 24px;
  background:
    radial-gradient(circle at 20% 0%, rgba(7, 193, 96, 0.06), transparent 40%),
    linear-gradient(180deg, #f1f5f9 0%, #e8edf3 100%);
}

.wechat-frame {
  max-width: 560px;
  margin: 0 auto;
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid #d1d5db;
  box-shadow: 0 20px 40px rgba(15, 23, 42, 0.12);
}

.wechat-topbar {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 14px 16px;
  background: linear-gradient(180deg, #393a3e 0%, #2e2f33 100%);
  color: #fff;
}

.wechat-topbar-title {
  font-size: 14px;
  font-weight: 600;
}

.wechat-topbar-sub {
  font-size: 10px;
  color: #9ca3af;
}

.chat-bubble {
  display: flex;
  gap: 10px;
  padding: 20px 16px;
  background: #ededed;
}

.chat-avatar {
  width: 36px;
  height: 36px;
  border-radius: 6px;
  background: linear-gradient(135deg, #07c160, #06ae56);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.chat-body {
  flex: 1;
  min-width: 0;
  padding: 12px 14px;
  border-radius: 4px 12px 12px 12px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

.chat-bubble-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 11px;
}

.chat-app {
  color: #07c160;
  font-weight: 700;
}

.chat-time { color: #9ca3af; }

.chat-title {
  margin-bottom: 12px;
  font-size: 16px;
  font-weight: 700;
  color: #111827;
  padding-bottom: 10px;
  border-bottom: 1px solid #f1f5f9;
}

.chat-section + .chat-section {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #f1f5f9;
}

.chat-section-title {
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
}

.chat-meta {
  margin-bottom: 4px;
  font-size: 11px;
  color: #9ca3af;
}

.chat-list {
  margin: 0;
  padding-left: 16px;
  color: #374151;
  font-size: 13px;
  line-height: 1.75;
}

.chat-empty {
  font-size: 13px;
  color: #9ca3af;
  font-style: italic;
}

.report-raw {
  max-width: 560px;
  margin: 16px auto 0;
}

.report-raw summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--text-secondary);
}

.report-raw pre {
  margin: 8px 0 0;
  padding: 12px;
  border-radius: 10px;
  background: #1e293b;
  color: #e2e8f0;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ── Result ── */
.result-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.result-line {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}

.result-line span {
  width: 72px;
  color: var(--text-secondary);
}

.result-line code {
  padding: 3px 10px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid #e8edf3;
  font-size: 12px;
}

@media (max-width: 1100px) {
  .wecom-grid {
    grid-template-columns: 1fr;
  }

  .panel-connection,
  .panel-daily,
  .panel-schedule,
  .panel-test,
  .panel-preview,
  .panel-result {
    grid-column: 1;
    grid-row: auto;
  }

  .switch-grid {
    grid-template-columns: 1fr;
  }

  .preview-editor-layout {
    grid-template-columns: 1fr;
  }

  .preview-editor {
    border-right: none;
    border-bottom: 1px solid #f1f5f9;
  }

  .status-hero {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
