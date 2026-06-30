<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type { WecomConfig, WecomHealth, WecomMsgType, WecomTestSendResult } from '@/types'

const loading = ref(false)
const saving = ref(false)
const sending = ref(false)
const health = ref<WecomHealth | null>(null)
const lastResult = ref<WecomTestSendResult | null>(null)

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

async function load() {
  loading.value = true
  try {
    const [cfg, h] = await Promise.all([api.wecomConfig(), api.wecomHealth()])
    health.value = h
    applyConfig(cfg)
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
          </el-form>
        </el-card>
      </el-col>

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
