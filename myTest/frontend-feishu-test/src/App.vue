<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  feishuApi,
  type FeishuConfigOut,
  type FeishuOAuthAuthorizeResult,
  type FeishuPreviewItem,
  type FeishuSyncResult,
} from './api'

const loading = ref(false)
const config = ref<FeishuConfigOut | null>(null)
const checkMessage = ref('')
const checkOk = ref<boolean | null>(null)
const oauthCode = ref('')
const oauthState = ref('')
const oauthAuthorize = ref<FeishuOAuthAuthorizeResult | null>(null)
const selectedDate = ref(new Date().toISOString().slice(0, 10))
const minimalFields = ref(true)
const previewItems = ref<FeishuPreviewItem[]>([])
const tableList = ref<{ table_id: string; name: string }[]>([])
const syncResult = ref<FeishuSyncResult | Record<string, unknown> | null>(null)
const lastAction = ref('')

async function runAction(label: string, fn: () => Promise<void>) {
  loading.value = true
  lastAction.value = label
  try {
    await fn()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败')
  } finally {
    loading.value = false
  }
}

async function loadConfig() {
  config.value = await feishuApi.config()
}

async function doCheck() {
  const res = await feishuApi.check()
  checkOk.value = res.ok
  checkMessage.value = res.message
  if (res.ok) ElMessage.success(res.message)
  else ElMessage.warning(res.message)
}

async function doGenerateAuthorizeUrl() {
  const res = await feishuApi.oauthAuthorizeUrl()
  oauthAuthorize.value = res
  oauthState.value = res.state
  ElMessage.success('授权链接已生成，可点击跳转授权页')
}

async function doExchangeCode() {
  if (!oauthCode.value.trim()) {
    ElMessage.warning('请先输入授权回调中的 code')
    return
  }
  const res = await feishuApi.oauthExchangeCode({
    code: oauthCode.value.trim(),
    state: oauthState.value.trim(),
    redirect_uri: config.value?.oauth_redirect_uri || '',
  })
  if (res.ok) {
    ElMessage.success(res.message)
    await loadConfig()
  } else {
    ElMessage.error(res.message)
  }
}

async function doInitTable() {
  const res = await feishuApi.initTable()
  ElMessage.success(`表已就绪: ${res.table_id}`)
  await loadConfig()
}

async function doPreview() {
  const res = await feishuApi.preview(selectedDate.value)
  previewItems.value = res.items
  ElMessage.success(`本地共 ${res.count} 条可同步记录`)
}

async function doListTables() {
  const res = await feishuApi.tables()
  tableList.value = res.items || []
  ElMessage.success(`Base 内共 ${res.count ?? tableList.value.length} 张表`)
}

async function doSync(dryRun: boolean) {
  const res = await feishuApi.sync({
    date: selectedDate.value,
    dry_run: dryRun,
    minimal_fields: minimalFields.value,
  })
  syncResult.value = res
  if (dryRun) {
    ElMessage.info(`预览：将写入 ${res.would_create ?? 0} 条`)
  } else {
    ElMessage.success(`已写入 ${res.created ?? 0} 条`)
  }
}

onMounted(() => {
  const params = new URLSearchParams(window.location.search)
  const code = params.get('code') || ''
  const state = params.get('state') || ''
  if (code) oauthCode.value = code
  if (state) oauthState.value = state
  runAction('加载配置', loadConfig)
})
</script>

<template>
  <div class="page">
    <header class="hero">
      <div>
        <h1>飞书上架日志 · 联调测试</h1>
        <p class="sub">
          独立测试环境：API <code>8001</code> · 前端 <code>5174</code> · 不接入主系统
        </p>
      </div>
      <el-tag type="warning" effect="dark">TEST ONLY</el-tag>
    </header>

    <el-row :gutter="16">
      <el-col :span="10">
        <el-card shadow="never" class="card">
          <template #header>配置与 OAuth 状态</template>
          <el-skeleton v-if="!config" :rows="5" animated />
          <el-descriptions v-else :column="1" border size="small">
            <el-descriptions-item label="配置文件">{{ config.config_path }}</el-descriptions-item>
            <el-descriptions-item label="App ID">{{ config.app_id || '未配置' }}</el-descriptions-item>
            <el-descriptions-item label="App Secret">{{ config.app_secret_masked || '未配置' }}</el-descriptions-item>
            <el-descriptions-item label="OAuth 回调">{{ config.oauth_redirect_uri || '未配置' }}</el-descriptions-item>
            <el-descriptions-item label="OAuth Scope">{{ config.oauth_scope || '未配置' }}</el-descriptions-item>
            <el-descriptions-item label="鉴权模式">
              {{ config.use_user_access_token ? 'user_access_token' : 'tenant_access_token' }}
            </el-descriptions-item>
            <el-descriptions-item label="用户令牌">{{ config.user_token_ready ? '已就绪' : '未授权' }}</el-descriptions-item>
            <el-descriptions-item label="Base Token">{{ config.bitable_app_token || '未配置' }}</el-descriptions-item>
            <el-descriptions-item label="Table ID">{{ config.table_id || '（init 后自动写入）' }}</el-descriptions-item>
            <el-descriptions-item label="表名">{{ config.table_name }}</el-descriptions-item>
            <el-descriptions-item label="标题列">{{ config.field_names.title }}</el-descriptions-item>
            <el-descriptions-item label="去重字段">{{ config.dedupe_field || '已关闭' }}</el-descriptions-item>
          </el-descriptions>

          <div class="actions">
            <el-button :loading="loading" @click="runAction('检查', async () => { await loadConfig(); await doCheck() })">
              检查 Token
            </el-button>
            <el-button :loading="loading" type="primary" plain @click="runAction('建表', doInitTable)">
              初始化数据表
            </el-button>
            <el-button :loading="loading" @click="runAction('刷新', loadConfig)">刷新配置</el-button>
            <el-button :loading="loading" @click="runAction('列表', doListTables)">列出 Base 表</el-button>
          </div>

          <el-divider />
          <el-form label-width="88px">
            <el-form-item label="第 1 步">
              <el-button :loading="loading" type="primary" @click="runAction('授权链接', doGenerateAuthorizeUrl)">
                生成授权链接
              </el-button>
              <a
                v-if="oauthAuthorize?.authorize_url"
                class="oauth-link"
                :href="oauthAuthorize.authorize_url"
                target="_blank"
                rel="noopener noreferrer"
              >
                打开飞书授权页
              </a>
            </el-form-item>
            <el-form-item label="第 2 步">
              <el-input
                v-model="oauthCode"
                placeholder="粘贴回调 URL 里的 code"
                clearable
              />
            </el-form-item>
            <el-form-item label="state">
              <el-input
                v-model="oauthState"
                placeholder="自动填入，可手动修改"
                clearable
              />
            </el-form-item>
            <el-form-item label="第 3 步">
              <el-button :loading="loading" type="success" @click="runAction('换取 user token', doExchangeCode)">
                code 换 user_access_token
              </el-button>
            </el-form-item>
          </el-form>

          <el-alert
            v-if="checkMessage"
            :title="checkMessage"
            :type="checkOk ? 'success' : 'error'"
            show-icon
            :closable="false"
            class="mt"
          />
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card shadow="never" class="card">
          <template #header>同步操作</template>

          <el-form label-width="110px">
            <el-form-item label="同步日期">
              <el-date-picker
                v-model="selectedDate"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择日期"
                style="width: 200px"
              />
            </el-form-item>
            <el-form-item label="字段模式">
              <el-switch
                v-model="minimalFields"
                active-text="仅标准 8 列（适配已有表）"
                inactive-text="含映射ID等扩展列"
              />
            </el-form-item>
          </el-form>

          <div class="actions">
            <el-button :loading="loading" @click="runAction('预览本地', doPreview)">预览本地数据</el-button>
            <el-button :loading="loading" type="info" @click="runAction('干跑', () => doSync(true))">
              干跑（不写飞书）
            </el-button>
            <el-button :loading="loading" type="danger" @click="runAction('写入飞书', () => doSync(false))">
              写入飞书
            </el-button>
          </div>

          <el-alert
            class="mt"
            type="info"
            :closable="false"
            show-icon
            title="建议流程：检查 Token → 填好 feishu.yaml 的 table_id → 预览本地 → 干跑 → 写入飞书"
          />
        </el-card>
      </el-col>
    </el-row>

    <el-card v-if="tableList.length" shadow="never" class="card mt">
      <template #header>Base 内数据表</template>
      <el-table :data="tableList" size="small" stripe>
        <el-table-column prop="name" label="表名" min-width="200" />
        <el-table-column prop="table_id" label="table_id" min-width="220" />
      </el-table>
    </el-card>

    <el-card v-if="previewItems.length" shadow="never" class="card mt">
      <template #header>本地预览（{{ previewItems.length }} 条）</template>
      <el-table :data="previewItems" size="small" stripe max-height="320">
        <el-table-column prop="account_id" label="店铺" width="100" />
        <el-table-column prop="product_code" label="编码" width="110" />
        <el-table-column prop="listing_label" label="标签" min-width="140" />
        <el-table-column prop="pdd_product_id" label="拼多多ID" width="130" />
        <el-table-column prop="published_at" label="发布时间" min-width="170" />
      </el-table>
    </el-card>

    <el-card v-if="syncResult" shadow="never" class="card mt">
      <template #header>最近结果（{{ lastAction }}）</template>
      <pre class="json">{{ JSON.stringify(syncResult, null, 2) }}</pre>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 28px 20px 48px;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
}

.hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 20px;
}

h1 {
  margin: 0 0 8px;
  font-size: 24px;
}

.sub {
  margin: 0;
  color: #64748b;
  font-size: 14px;
}

.card {
  border-radius: 12px;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}

.oauth-link {
  margin-left: 12px;
  color: #2563eb;
  text-decoration: none;
}

.oauth-link:hover {
  text-decoration: underline;
}

.mt {
  margin-top: 16px;
}

.json {
  margin: 0;
  padding: 12px;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  font-size: 12px;
  overflow: auto;
  max-height: 360px;
}

code {
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
}
</style>
