<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
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
const previewPlatform = ref<WecomDailyReportPlatform>('pdd')
const reportPreview = ref<WecomDailyReportPreview | null>(null)

const webhookMasked = ref('')
const webhookConfigured = ref(false)
const webhookEditing = ref(false)
const webhookDraft = ref('')

const configForm = reactive({
  enabled: false,
  notify_on_listing_failed: false,
  notify_on_pipeline_failed: false,
  notify_on_commerce_queued: false,
  notify_on_commerce_dispatched: false,
  daily_report_schedule_enabled: false,
  daily_report_schedule_hour: 18,
  daily_report_schedule_minute: 0,
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
  configForm.notify_on_listing_failed = cfg.notify_on_listing_failed
  configForm.notify_on_pipeline_failed = cfg.notify_on_pipeline_failed
  configForm.notify_on_commerce_queued = cfg.notify_on_commerce_queued
  configForm.notify_on_commerce_dispatched = cfg.notify_on_commerce_dispatched
  configForm.daily_report_schedule_enabled = cfg.daily_report_schedule_enabled
  configForm.daily_report_schedule_hour = cfg.daily_report_schedule_hour
  configForm.daily_report_schedule_minute = cfg.daily_report_schedule_minute
  scheduleLastRunDate.value = cfg.daily_report_last_run_date || ''
  scheduleRunning.value = Boolean(cfg.daily_report_scheduler_running)
  webhookEditing.value = false
  webhookDraft.value = ''
}

function startWebhookEdit() {
  webhookEditing.value = true
  webhookDraft.value = ''
}

function cancelWebhookEdit() {
  webhookEditing.value = false
  webhookDraft.value = ''
}

function applyDailyContent(data: {
  content_date: string
  pdd_in_progress: string
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
}

async function load() {
  loading.value = true
  try {
    const [cfg, h, dailyContent] = await Promise.all([
      api.wecomConfig(),
      api.wecomHealth(),
      api.wecomDailyContent(),
    ])
    health.value = h
    applyConfig(cfg)
    applyDailyContent(dailyContent)
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
    const cfg = await api.updateWecomConfig({
      enabled: configForm.enabled,
      webhook_url: webhookUrl,
      notify_on_listing_failed: configForm.notify_on_listing_failed,
      notify_on_pipeline_failed: configForm.notify_on_pipeline_failed,
      notify_on_commerce_queued: configForm.notify_on_commerce_queued,
      notify_on_commerce_dispatched: configForm.notify_on_commerce_dispatched,
      daily_report_schedule_enabled: configForm.daily_report_schedule_enabled,
      daily_report_schedule_hour: configForm.daily_report_schedule_hour,
      daily_report_schedule_minute: configForm.daily_report_schedule_minute,
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
    reportPreview.value = await api.wecomDailyReportPreview(platform)
  } catch (e) {
    if (!(e instanceof Error)) {
      ElMessage.error('预览失败')
    }
  } finally {
    previewing.value = false
  }
}

async function triggerDailyReport(platform: WecomDailyReportPlatform) {
  const loadingRef = platform === 'pdd' ? triggeringPddReport : triggeringTaobaoReport
  loadingRef.value = true
  try {
    await saveDailyContent(true)
    const result = await api.wecomDailyReportTrigger({ platform })
    if (result.ok) {
      ElMessage.success(result.message || '日报已发送')
      if (platform === 'pdd') {
        const cfg = await api.wecomConfig()
        applyConfig(cfg)
      }
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

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page" v-loading="loading">
    <PageHeader
      title="企业微信通知"
      subtitle="配置群 Webhook，测试消息推送，并可开启上架/链路失败自动通知"
    />

    <el-alert
      :type="statusType"
      :closable="false"
      show-icon
      class="status-bar"
      :title="statusLabel"
    >
      <template v-if="health">
        配置文件：{{ health.config_path || '—' }}
        <span v-if="health.webhook_configured && !health.enabled">
          · 保存并启用后即可自动/手动推送
        </span>
      </template>
    </el-alert>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="12">
        <el-card shadow="never" class="card">
          <template #header>
            <div class="card-head">
              <span>连接配置</span>
              <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
            </div>
          </template>

          <el-form label-position="top">
            <el-form-item label="启用企业微信通知">
              <el-switch v-model="configForm.enabled" />
            </el-form-item>

            <el-form-item label="Webhook 地址">
              <template v-if="!webhookEditing">
                <div class="webhook-mask-row">
                  <el-input
                    :model-value="webhookConfigured ? webhookMasked : ''"
                    readonly
                    placeholder="尚未配置 Webhook"
                  />
                  <el-button @click="startWebhookEdit">
                    {{ webhookConfigured ? '更换' : '填写' }}
                  </el-button>
                </div>
                <div class="hint">
                  地址已脱敏显示，仅保存于服务端配置文件。点击「更换」可填入新地址；不更换则保留原地址。
                </div>
              </template>
              <template v-else>
                <el-input
                  v-model="webhookDraft"
                  type="textarea"
                  :rows="3"
                  placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
                />
                <div class="webhook-edit-actions">
                  <el-button link type="primary" @click="cancelWebhookEdit">取消更换</el-button>
                </div>
                <div class="hint">
                  在企业微信群「聊天信息 → 消息推送 → 添加」后粘贴完整 Webhook。留空保存将保留已有地址。
                </div>
              </template>
            </el-form-item>

            <el-divider content-position="left">自动通知</el-divider>

            <el-form-item label="上架失败时推送">
              <el-switch v-model="configForm.notify_on_listing_failed" />
            </el-form-item>

            <el-form-item label="整合链路失败时推送">
              <el-switch v-model="configForm.notify_on_pipeline_failed" />
            </el-form-item>

            <el-form-item label="运营任务排队时推送">
              <el-switch v-model="configForm.notify_on_commerce_queued" />
            </el-form-item>

            <el-form-item label="排队任务派发时推送">
              <el-switch v-model="configForm.notify_on_commerce_dispatched" />
            </el-form-item>

            <el-divider content-position="left">定时任务</el-divider>

            <el-form-item label="启用 PDD 日报定时发送">
              <el-switch v-model="configForm.daily_report_schedule_enabled" />
              <div class="hint">
                仅自动发送 PDD 日报。淘宝日报请手动发送。
              </div>
            </el-form-item>

            <el-form-item label="每天发送时间">
              <div class="time-row">
                <el-input-number
                  v-model="configForm.daily_report_schedule_hour"
                  :min="0"
                  :max="23"
                  controls-position="right"
                />
                <span class="time-sep">时</span>
                <el-input-number
                  v-model="configForm.daily_report_schedule_minute"
                  :min="0"
                  :max="59"
                  controls-position="right"
                />
                <span class="time-sep">分</span>
                <el-tag type="info">{{ scheduleTimeDisplay }}（Asia/Shanghai）</el-tag>
              </div>
              <div class="hint">
                默认 18:00。店铺发布进度统计窗口为昨天 18:01 ~ 今天 17:00。
              </div>
            </el-form-item>

            <el-form-item label="调度状态">
              <div class="schedule-status">
                <el-tag :type="scheduleRunning ? 'success' : 'info'">
                  {{ scheduleRunning ? '调度器运行中' : '调度器未启动' }}
                </el-tag>
                <span v-if="scheduleLastRunDate" class="schedule-meta">
                  上次 PDD 自动发送：{{ scheduleLastRunDate }}
                </span>
                <span v-else class="schedule-meta">今天尚未自动发送 PDD 日报</span>
              </div>
              <div class="report-actions">
                <el-button
                  type="warning"
                  plain
                  :loading="triggeringPddReport"
                  @click="triggerDailyReport('pdd')"
                >
                  立即发送 PDD 日报
                </el-button>
                <el-button
                  type="primary"
                  plain
                  :loading="triggeringTaobaoReport"
                  @click="triggerDailyReport('taobao')"
                >
                  立即发送淘宝日报
                </el-button>
              </div>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="12">
        <el-card shadow="never" class="card">
          <template #header>
            <div class="card-head">
              <span>日报内容（每日填写）</span>
              <el-button type="primary" :loading="savingDailyContent" @click="saveDailyContent()">
                保存日报内容
              </el-button>
            </div>
          </template>

          <el-form label-position="top">
            <el-alert
              :type="dailyContentDbAvailable ? 'info' : 'warning'"
              :closable="false"
              show-icon
              class="content-tip"
            >
              <template v-if="dailyContentDbAvailable">
                按自然日存 MySQL：今天填写会覆盖今天记录；今天未保存则发送时对应区块为空（不会沿用昨天）。
                <span v-if="dailyContentDate">当前日期：{{ dailyContentDate }}</span>
                <span v-if="dailyContentUpdatedAt"> · 最近保存：{{ dailyContentUpdatedAt }}</span>
              </template>
              <template v-else>
                数据库不可用，无法保存日报手动内容。
              </template>
            </el-alert>

            <el-divider content-position="left">PDD</el-divider>

            <el-form-item label="正在解决/优化中">
              <el-input
                v-model="dailyContentForm.pdd_in_progress"
                type="textarea"
                :rows="4"
                placeholder="例如：修复上架超时问题"
              />
            </el-form-item>

            <el-divider content-position="left">淘宝</el-divider>

            <el-form-item label="网盘素材和上架累计数据">
              <el-input
                v-model="dailyContentForm.taobao_netdisk_materials"
                type="textarea"
                :rows="5"
                placeholder="填写今日网盘素材和上架累计数据"
              />
            </el-form-item>

            <el-form-item label="正在解决/优化中">
              <el-input
                v-model="dailyContentForm.taobao_in_progress"
                type="textarea"
                :rows="4"
                placeholder="填写淘宝侧正在处理的事项"
              />
            </el-form-item>

            <div v-if="dailyContentDate" class="hint">
              保存目标日期：{{ dailyContentDate }}（Asia/Shanghai 今天）
            </div>

            <div class="report-actions">
              <el-button :loading="previewing && previewPlatform === 'pdd'" @click="previewDailyReport('pdd')">
                预览 PDD 日报
              </el-button>
              <el-button :loading="previewing && previewPlatform === 'taobao'" @click="previewDailyReport('taobao')">
                预览淘宝日报
              </el-button>
            </div>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="12">
        <el-card shadow="never" class="card">
          <template #header>
            <div class="card-head">
              <span>发送测试</span>
              <el-button type="success" :loading="sending" @click="sendTest">发送测试消息</el-button>
            </div>
          </template>

          <el-form label-position="top">
            <el-form-item label="消息类型">
              <el-radio-group v-model="testForm.msgtype">
                <el-radio-button value="text">文本</el-radio-button>
                <el-radio-button value="markdown">Markdown</el-radio-button>
                <el-radio-button value="markdown_v2">Markdown v2</el-radio-button>
                <el-radio-button value="raw">原始 JSON</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <el-form-item v-if="testForm.msgtype !== 'raw'" label="消息内容">
              <el-input v-model="testForm.content" type="textarea" :rows="6" />
              <div class="sample-actions">
                <el-button link type="primary" @click="fillMarkdownSample">填入 Markdown 样例</el-button>
                <el-button link type="primary" @click="fillMarkdownV2Sample">填入 Markdown v2 样例</el-button>
              </div>
            </el-form-item>

            <el-form-item v-if="testForm.msgtype === 'raw'" label="原始 JSON 消息体">
              <el-input v-model="testForm.raw_json" type="textarea" :rows="10" class="mono" />
              <div class="hint">
                支持企业微信官方任意 msgtype，如 text / markdown / news / template_card 等。
              </div>
            </el-form-item>

            <el-form-item label="Webhook 来源">
              <el-switch
                v-model="testForm.use_saved_webhook"
                active-text="使用已保存的 Webhook"
                inactive-text="临时指定 Webhook"
              />
            </el-form-item>

            <el-form-item v-if="!testForm.use_saved_webhook" label="临时 Webhook">
              <el-input v-model="testForm.override_webhook_url" placeholder="仅本次测试使用" />
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <el-card v-if="reportPreview" shadow="never" class="card result-card" v-loading="previewing">
      <template #header>
        <div class="card-head">
          <span>日报预览（{{ reportPreview.platform === 'pdd' ? 'PDD' : '淘宝' }}）</span>
          <el-tag type="info">{{ reportPreview.report_date }}</el-tag>
        </div>
      </template>
      <pre class="report-preview">{{ reportPreview.message }}</pre>
    </el-card>

    <el-card v-if="lastResult" shadow="never" class="card result-card">
      <template #header>最近一次发送结果</template>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="状态">
          <el-tag :type="lastResult.ok ? 'success' : 'danger'">
            {{ lastResult.ok ? '成功' : '失败' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="errcode">{{ lastResult.errcode }}</el-descriptions-item>
        <el-descriptions-item label="errmsg">{{ lastResult.errmsg || '—' }}</el-descriptions-item>
      </el-descriptions>
      <div class="json-block">
        <div class="json-title">请求体</div>
        <pre>{{ JSON.stringify(lastResult.payload_sent, null, 2) }}</pre>
      </div>
      <div class="json-block">
        <div class="json-title">响应</div>
        <pre>{{ JSON.stringify(lastResult.response, null, 2) }}</pre>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.status-bar {
  margin-bottom: 0;
}

.card {
  margin-bottom: 16px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.hint code {
  padding: 0 4px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}

.webhook-mask-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.webhook-mask-row .el-input {
  flex: 1;
}

.webhook-edit-actions {
  margin-top: 4px;
}

.time-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.time-sep {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.schedule-status {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.schedule-meta {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.content-tip {
  margin-bottom: 12px;
}

.report-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.report-preview {
  margin: 0;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  overflow: auto;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.sample-actions {
  margin-top: 6px;
  display: flex;
  gap: 12px;
}

.mono :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.result-card pre {
  margin: 0;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  overflow: auto;
  font-size: 12px;
}

.json-block {
  margin-top: 12px;
}

.json-title {
  margin-bottom: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
</style>
