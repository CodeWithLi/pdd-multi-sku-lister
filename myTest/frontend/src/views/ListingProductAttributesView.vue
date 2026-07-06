<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type { ListingProductAttribute } from '@/types'

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const items = ref<ListingProductAttribute[]>([])
const formValues = reactive<Record<string, string>>({})

const enabledItems = computed(() => items.value.filter((item) => item.enabled))

const leftColumnItems = computed(() =>
  enabledItems.value.filter((_, index) => index % 2 === 0),
)

const rightColumnItems = computed(() =>
  enabledItems.value.filter((_, index) => index % 2 === 1),
)

function syncFormValues(rows: ListingProductAttribute[]) {
  for (const key of Object.keys(formValues)) {
    delete formValues[key]
  }
  for (const row of rows) {
    if (row.enabled) {
      formValues[row.field_key] = row.selected_value || ''
    }
  }
}

async function loadAttributes() {
  loading.value = true
  error.value = ''
  try {
    const resp = await api.listingProductAttributes({ enabled_only: true })
    items.value = resp.items
    syncFormValues(resp.items)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载商品属性失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const resp = await api.updateListingProductAttributes({
      attributes: { ...formValues },
    })
    items.value = resp.items
    syncFormValues(resp.items)
    ElMessage.success('商品属性已保存')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(loadAttributes)
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="商品属性"
      desc="配置拼多多发布页「商品属性」下拉选项的默认值。后续上架时会按此处配置自动填写；是否透明、是否有夹层、产品类型暂未启用。"
    >
      <template #actions>
        <el-button @click="loadAttributes">刷新</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      closable
      style="margin-bottom: 16px"
      @close="error = ''"
    />

    <el-card shadow="never" class="stat-card">
      <el-empty v-if="!enabledItems.length && !loading" description="暂无可用商品属性，请确认 MySQL 已连接" />

      <el-form v-else label-position="top" class="attr-form">
        <el-row :gutter="24">
          <el-col :span="12">
            <el-form-item
              v-for="item in leftColumnItems"
              :key="item.field_key"
              :label="item.label"
              required
            >
              <el-select
                v-model="formValues[item.field_key]"
                filterable
                allow-create
                default-first-option
                placeholder="请选择"
                style="width: 100%"
              >
                <el-option
                  v-for="opt in item.options"
                  :key="`${item.field_key}-${opt}`"
                  :label="opt"
                  :value="opt"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item
              v-for="item in rightColumnItems"
              :key="item.field_key"
              :label="item.label"
              required
            >
              <el-select
                v-model="formValues[item.field_key]"
                filterable
                allow-create
                default-first-option
                placeholder="请选择"
                style="width: 100%"
              >
                <el-option
                  v-for="opt in item.options"
                  :key="`${item.field_key}-${opt}`"
                  :label="opt"
                  :value="opt"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.attr-form {
  max-width: 960px;
}

.attr-form :deep(.el-form-item__label) {
  font-weight: 500;
}
</style>
