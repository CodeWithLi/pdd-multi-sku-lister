<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/api/client'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)

type ListingTargetOption = {
  selector: string
  family_code: string
  image_set: string
  product_codes: string[]
  product_count: number
}

const listingTargetsLoading = ref(false)
const listingTargets = ref<ListingTargetOption[]>([])
const testResult = ref<{ title: string; reason: string; images: string[]; source: string }>({
  title: '',
  reason: '',
  images: [],
  source: '',
})

const form = reactive({
  enabled: false,
  provider: 'deepseek',
  model: 'deepseek-chat',
  base_url: 'https://api.deepseek.com/v1',
  fallback_enabled: true,
  fallback_provider: 'glm',
  fallback_model: 'glm-4-flash',
  fallback_base_url: 'https://open.bigmodel.cn/api/paas/v4',
  prompt: '',
  temperature: 0.3,
  max_image_count: 3,
  api_key: '',
  has_api_key: false,
  fallback_api_key: '',
  has_fallback_api_key: false,
})

const testForm = reactive({
  selector: '',
  product_code: '',
  category_keyword: '',
  current_title: '',
  material_source: 'local' as 'local' | 'minio',
})

const selectedTarget = computed(() => {
  const sel = String(testForm.selector || '').trim()
  return listingTargets.value.find((t) => t.selector === sel) || null
})

const targetProductOptions = computed(() => {
  const codes = selectedTarget.value?.product_codes || []
  return codes.slice().sort((a, b) => a.localeCompare(b))
})

function assetPreviewUrl(path: string) {
  return `/api/catalog/asset?path=${encodeURIComponent(path)}&material_source=${encodeURIComponent(
    testForm.material_source,
  )}`
}

async function loadConfig() {
  loading.value = true
  try {
    const data = await api.getPipelineSubmitAiTitle()
    form.enabled = !!data.enabled
    form.provider = String(data.provider || 'deepseek')
    form.model = String(data.model || 'deepseek-chat')
    form.base_url = String(data.base_url || 'https://api.deepseek.com/v1')
    form.fallback_enabled = !!data.fallback_enabled
    form.fallback_provider = String(data.fallback_provider || 'glm')
    form.fallback_model = String(data.fallback_model || 'glm-4-flash')
    form.fallback_base_url = String(data.fallback_base_url || 'https://open.bigmodel.cn/api/paas/v4')
    form.prompt = String(data.prompt || '')
    form.temperature = Number(data.temperature ?? 0.3)
    form.max_image_count = Number(data.max_image_count ?? 3)
    form.has_api_key = !!data.has_api_key
    form.has_fallback_api_key = !!data.has_fallback_api_key
    form.api_key = ''
    form.fallback_api_key = ''
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    loading.value = false
  }
}

async function loadListingTargets() {
  listingTargetsLoading.value = true
  try {
    const data = await api.listingTargets(undefined, testForm.material_source)
    listingTargets.value = (data || []) as ListingTargetOption[]
    if (!testForm.selector && listingTargets.value.length) {
      testForm.selector = listingTargets.value[0].selector
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    listingTargetsLoading.value = false
  }
}

async function saveConfig() {
  saving.value = true
  try {
    const payload: Record<string, unknown> = {
      enabled: form.enabled,
      provider: form.provider,
      model: form.model,
      base_url: form.base_url,
      fallback_enabled: form.fallback_enabled,
      fallback_provider: form.fallback_provider,
      fallback_model: form.fallback_model,
      fallback_base_url: form.fallback_base_url,
      prompt: form.prompt,
      temperature: Number(form.temperature),
      max_image_count: Number(form.max_image_count),
    }
    if (form.api_key.trim()) payload.api_key = form.api_key.trim()
    if (form.fallback_api_key.trim()) payload.fallback_api_key = form.fallback_api_key.trim()
    const data = await api.updatePipelineSubmitAiTitle(payload)
    form.enabled = !!data.enabled
    form.has_api_key = !!data.has_api_key
    form.has_fallback_api_key = !!data.has_fallback_api_key
    form.api_key = ''
    form.fallback_api_key = ''
    ElMessage.success('提交前 AI 标题配置已保存')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    saving.value = false
  }
}

async function runTest() {
  const selector = String(testForm.selector || '').trim()
  if (!selector) {
    ElMessage.error('请选择要测试的套图')
    return
  }
  testing.value = true
  testResult.value = { title: '', reason: '', images: [], source: '' }
  ElMessage.info('正在解析素材并调用 AI，请稍候…')
  try {
    const res = await api.testPipelineSubmitAiTitle({
      selector,
      product_code: String(testForm.product_code || '').trim() || undefined,
      category_keyword: String(testForm.category_keyword || '').trim() || undefined,
      current_title: String(testForm.current_title || '').trim() || undefined,
      material_source: testForm.material_source,
    })
    testResult.value = {
      title: String(res.title || ''),
      reason: String(res.reason || ''),
      images: Array.isArray(res.images_used) ? res.images_used.map(String) : [],
      source: String(res.source || ''),
    }
    if (res.applied && res.title) {
      ElMessage.success('测试生成成功')
    } else {
      ElMessage.warning(`测试未生成标题：${res.reason || 'unknown'}`)
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    testing.value = false
  }
}

onMounted(async () => {
  await loadConfig()
  await loadListingTargets()
})
</script>

<template>
  <div class="page">
    <PageHeader
      title="提交前 AI 标题配置"
      description="独立于历史 page_ai 流程；在运费模板设置完成后、提交前执行 AI 改标题。"
    />

    <el-card shadow="never" v-loading="loading">
      <el-form label-width="140px">
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>

        <el-form-item label="厂商 provider">
          <el-input v-model="form.provider" placeholder="deepseek / openai / 其他兼容厂商" />
        </el-form-item>

        <el-form-item label="模型 model">
          <el-input v-model="form.model" placeholder="例如 deepseek-chat / deepseek-vision(需支持图片)" />
          <div class="form-tip">
            如果要“根据图片生成标题”，请确保你填的模型本身支持图片输入（否则会报不支持 image_url）。
          </div>
        </el-form-item>

        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="例如 https://api.deepseek.com/v1" />
        </el-form-item>

        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            placeholder="留空表示不修改当前密钥"
          />
          <div class="form-tip">
            当前密钥状态：{{ form.has_api_key ? '已配置' : '未配置' }}
          </div>
        </el-form-item>

        <el-divider content-position="left">兜底模型（主模型失败自动调用）</el-divider>

        <el-form-item label="启用兜底">
          <el-switch v-model="form.fallback_enabled" />
        </el-form-item>

        <el-form-item label="兜底 provider">
          <el-input v-model="form.fallback_provider" placeholder="glm / openai / 其他兼容厂商" />
        </el-form-item>

        <el-form-item label="兜底 model">
          <el-input v-model="form.fallback_model" placeholder="例如 glm-4-flash" />
        </el-form-item>

        <el-form-item label="兜底 Base URL">
          <el-input v-model="form.fallback_base_url" placeholder="例如 https://open.bigmodel.cn/api/paas/v4" />
        </el-form-item>

        <el-form-item label="兜底 API Key">
          <el-input
            v-model="form.fallback_api_key"
            type="password"
            show-password
            placeholder="留空表示不修改当前兜底密钥"
          />
          <div class="form-tip">
            当前兜底密钥状态：{{ form.has_fallback_api_key ? '已配置' : '未配置' }}
          </div>
        </el-form-item>

        <el-form-item label="Temperature">
          <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" />
        </el-form-item>

        <el-form-item label="图片数量上限">
          <el-input-number v-model="form.max_image_count" :min="1" :max="5" />
        </el-form-item>

        <el-form-item label="提示词">
          <el-input
            v-model="form.prompt"
            type="textarea"
            :rows="8"
            placeholder="请输入用于提交前改标题的提示词"
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="saving" @click="saveConfig">保存配置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <div class="card-title">测试：选某套图生成标题</div>
          <div class="card-sub">用于验证 DeepSeek/其他兼容模型是否支持图片输入</div>
        </div>
      </template>

      <el-form label-width="140px" v-loading="listingTargetsLoading">
        <el-form-item label="素材来源">
          <el-radio-group
            v-model="testForm.material_source"
            @change="
              () => {
                testForm.selector = ''
                testForm.product_code = ''
                loadListingTargets()
              }
            "
          >
            <el-radio-button label="local">本地</el-radio-button>
            <el-radio-button label="minio">MinIO 缓存</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="选择套图">
          <el-select v-model="testForm.selector" filterable placeholder="选择 BDxxx/第一套图" style="width: 520px">
            <el-option
              v-for="opt in listingTargets"
              :key="opt.selector"
              :label="`${opt.selector}（${opt.product_count} 个商品）`"
              :value="opt.selector"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="指定商品(可选)">
          <el-select
            v-model="testForm.product_code"
            clearable
            filterable
            placeholder="留空则用该套图第一个商品"
            style="width: 520px"
          >
            <el-option v-for="code in targetProductOptions" :key="code" :label="code" :value="code" />
          </el-select>
        </el-form-item>

        <el-form-item label="类目关键词(可选)">
          <el-input v-model="testForm.category_keyword" placeholder="例如 笔袋 / 文具收纳" style="width: 520px" />
        </el-form-item>

        <el-form-item label="当前标题(可选)">
          <el-input v-model="testForm.current_title" placeholder="用于测试“已生成标题时必须换卖点”" />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="testing" @click="runTest">开始测试生成</el-button>
          <div v-if="testResult.source" class="form-tip">来源：{{ testResult.source }}</div>
        </el-form-item>

        <el-form-item v-if="testResult.title" label="生成结果">
          <el-input :model-value="testResult.title" type="textarea" :rows="3" readonly />
        </el-form-item>
        <el-form-item v-else-if="testResult.reason" label="未生成原因">
          <el-alert :title="testResult.reason" type="warning" :closable="false" />
        </el-form-item>

        <el-form-item v-if="testResult.images.length" label="使用图片">
          <div class="image-grid">
            <el-image
              v-for="(img, idx) in testResult.images"
              :key="img"
              :src="assetPreviewUrl(img)"
              :preview-src-list="testResult.images.map(assetPreviewUrl)"
              :initial-index="idx"
              fit="cover"
              class="thumb"
            />
          </div>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-tip {
  margin-top: 6px;
  color: var(--text-secondary);
  font-size: 12px;
}

.card-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.card-title {
  font-weight: 600;
}

.card-sub {
  color: var(--text-secondary);
  font-size: 12px;
}

.image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(96px, 1fr));
  gap: 10px;
  width: 100%;
}

.thumb {
  width: 96px;
  height: 96px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--el-border-color);
}
</style>
