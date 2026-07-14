<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type { ConfigSummary, RuntimeConfig } from '@/types'

const loading = ref(false)
const saving = ref(false)
const summary = ref<ConfigSummary | null>(null)

const form = reactive<RuntimeConfig>({
  app: { name: 'dy-agent-platform', log_level: 'INFO' },
  login: { sms_wait_seconds: 300, auto_send_sms: true },
  paths: {
    assets_root: 'data/assets/商品上架规格文件',
    profiles_root: 'data/profiles',
    runs_root: 'data/runs',
  },
  browser: {
    headless: false,
    slow_mo: 0,
    default_timeout_ms: 30000,
    base_url: 'https://fxg.jinritemai.com',
    channel: '',
  },
  multi_spec: { excel: 'data/assets/抖音所有商品.xls', defaults: {} },
  listing: {
    category_keyword: '玩偶',
    title_mode: 'page_ai',
    brand_name: '无品牌',
    manufacturer_name: '',
    slot_alignment_test: false,
    spec_fill_verify_test: true,
    primary_style_first_test: true,
    category_next_burst_demo: true,
    accessory_cost_pricing: true,
    accessory_tiered_float: true,
  },
})

function applyConfig(cfg: RuntimeConfig) {
  form.app = { ...cfg.app }
  form.login = { ...cfg.login }
  form.paths = { ...cfg.paths }
  form.browser = { ...cfg.browser }
  form.multi_spec = { excel: cfg.multi_spec.excel, defaults: { ...cfg.multi_spec.defaults } }
  form.listing = {
    ...form.listing,
    ...cfg.listing,
    brand_name: cfg.listing.brand_name || '无品牌',
    manufacturer_name: cfg.listing.manufacturer_name || '',
  }
}

async function load() {
  loading.value = true
  try {
    const [cfg, sum] = await Promise.all([api.runtimeConfig(), api.configSummary()])
    applyConfig(cfg)
    summary.value = sum
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载配置失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    applyConfig(await api.updateRuntimeConfig(JSON.parse(JSON.stringify(form))))
    ElMessage.success('配置已保存')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="系统设置" desc="维护素材路径、浏览器参数与上架规则。">
      <template #actions>
        <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="summary"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 16px"
    >
      <template #title>运行环境</template>
      <template #default>
        LLM {{ summary.llm_configured ? '已配置' : '未配置' }} ·
        MySQL {{ summary.database_configured ? (summary.database_available ? '已连接' : '未连接') : '未配置' }}
        <span v-if="summary.database_name">（{{ summary.database_name }}）</span>
      </template>
    </el-alert>

    <el-card shadow="never" class="stat-card" style="margin-bottom: 16px">
      <template #header>登录</template>
      <el-form label-position="top" class="settings-form">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="短信验证码等待秒数">
              <el-input-number v-model="form.login.sms_wait_seconds" :min="30" :max="600" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="自动点击发送验证码">
              <el-switch v-model="form.login.auto_send_sms" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-card shadow="never" class="stat-card" style="margin-bottom: 16px">
      <template #header>路径</template>
      <el-form label-position="top" class="settings-form">
        <el-form-item label="素材根目录">
          <el-input v-model="form.paths.assets_root" />
        </el-form-item>
        <el-form-item label="浏览器 Profile 目录">
          <el-input v-model="form.paths.profiles_root" />
        </el-form-item>
        <el-form-item label="运行记录目录">
          <el-input v-model="form.paths.runs_root" />
        </el-form-item>
        <el-form-item label="多规格 Excel">
          <el-input v-model="form.multi_spec.excel" />
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="stat-card" style="margin-bottom: 16px">
      <template #header>浏览器</template>
      <el-form label-position="top" class="settings-form">
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="无头模式">
              <el-switch v-model="form.browser.headless" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="慢动作(ms)">
              <el-input-number v-model="form.browser.slow_mo" :min="0" :max="2000" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="超时(ms)">
              <el-input-number v-model="form.browser.default_timeout_ms" :min="5000" :max="120000" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="抖店后台 URL">
          <el-input v-model="form.browser.base_url" />
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="stat-card">
      <template #header>上架规则</template>
      <el-form label-position="top" class="settings-form">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="类目关键词">
              <el-input v-model="form.listing.category_keyword" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="标题模式">
              <el-select v-model="form.listing.title_mode" style="width: 100%">
                <el-option label="页面 AI 标题" value="page_ai" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="品牌（类目属性）">
              <el-input v-model="form.listing.brand_name" placeholder="无品牌" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="生产企业名称">
              <el-input v-model="form.listing.manufacturer_name" placeholder="必填文本框内容" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="试验开关">
          <div class="flag-grid">
            <el-checkbox v-model="form.listing.slot_alignment_test">槽位对齐</el-checkbox>
            <el-checkbox v-model="form.listing.spec_fill_verify_test">规格填表校验</el-checkbox>
            <el-checkbox v-model="form.listing.primary_style_first_test">主款优先</el-checkbox>
            <el-checkbox v-model="form.listing.category_next_burst_demo">类目连点下一步</el-checkbox>
            <el-checkbox v-model="form.listing.accessory_cost_pricing">配件成本定价</el-checkbox>
            <el-checkbox v-model="form.listing.accessory_tiered_float">配件阶梯浮动</el-checkbox>
          </div>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.settings-form { max-width: 760px; }
.flag-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px; }
</style>
