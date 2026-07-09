<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import { api } from '@/api/client'

const loading = ref(false)
const saving = ref(false)

const form = reactive({
  enabled: false,
  provider: 'deepseek',
  model: 'deepseek-chat',
  base_url: 'https://api.deepseek.com/v1',
  prompt: '',
  temperature: 0.3,
  max_image_count: 3,
  api_key: '',
  has_api_key: false,
})

async function loadConfig() {
  loading.value = true
  try {
    const data = await api.getPipelineSubmitAiTitle()
    form.enabled = !!data.enabled
    form.provider = String(data.provider || 'deepseek')
    form.model = String(data.model || 'deepseek-chat')
    form.base_url = String(data.base_url || 'https://api.deepseek.com/v1')
    form.prompt = String(data.prompt || '')
    form.temperature = Number(data.temperature ?? 0.3)
    form.max_image_count = Number(data.max_image_count ?? 3)
    form.has_api_key = !!data.has_api_key
    form.api_key = ''
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    loading.value = false
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
      prompt: form.prompt,
      temperature: Number(form.temperature),
      max_image_count: Number(form.max_image_count),
    }
    if (form.api_key.trim()) payload.api_key = form.api_key.trim()
    const data = await api.updatePipelineSubmitAiTitle(payload)
    form.enabled = !!data.enabled
    form.has_api_key = !!data.has_api_key
    form.api_key = ''
    ElMessage.success('提交前 AI 标题配置已保存')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    saving.value = false
  }
}

onMounted(loadConfig)
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
          <el-input v-model="form.model" placeholder="例如 deepseek-chat" />
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
</style>
