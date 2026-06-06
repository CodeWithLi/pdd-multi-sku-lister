<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type { Account, AccountDetail } from '@/types'

const loading = ref(false)
const accounts = ref<Account[]>([])
const dialogVisible = ref(false)
const isEdit = ref(false)
const saving = ref(false)

const form = reactive({
  account_id: '',
  enabled: true,
  username: '',
  password: '',
  product_codes: [] as string[],
})

const productOptions = ref<string[]>([])

async function load() {
  loading.value = true
  try {
    const [accs, prods] = await Promise.all([api.accounts(), api.products()])
    accounts.value = accs
    productOptions.value = prods.map((p) => p.product_code)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.account_id = ''
  form.enabled = true
  form.username = ''
  form.password = ''
  form.product_codes = []
}

function openCreate() {
  isEdit.value = false
  resetForm()
  dialogVisible.value = true
}

async function openEdit(row: Account) {
  isEdit.value = true
  loading.value = true
  try {
    const detail: AccountDetail = await api.accountDetail(row.account_id)
    form.account_id = detail.account_id
    form.enabled = detail.enabled
    form.username = detail.username
    form.password = detail.password
    form.product_codes = [...detail.product_codes]
    dialogVisible.value = true
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!isEdit.value && !form.account_id.trim()) {
    ElMessage.warning('请填写店铺名称')
    return
  }
  saving.value = true
  try {
    if (isEdit.value) {
      await api.updateAccount(form.account_id, {
        enabled: form.enabled,
        username: form.username,
        password: form.password,
        product_codes: form.product_codes,
      })
      ElMessage.success('已保存')
    } else {
      await api.createAccount({
        account_id: form.account_id.trim(),
        enabled: form.enabled,
        username: form.username,
        password: form.password,
        product_codes: form.product_codes,
      })
      ElMessage.success('店铺已添加')
    }
    dialogVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(row: Account) {
  try {
    await ElMessageBox.confirm(
      `确定删除店铺「${row.account_id}」吗？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await api.deleteAccount(row.account_id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error(e instanceof Error ? e.message : '删除失败')
    }
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="店铺设置" desc="配置拼多多登录账号。每个店铺独立保存登录状态，互不影响。">
      <template #actions>
        <el-button type="primary" @click="openCreate">+ 添加店铺</el-button>
      </template>
    </PageHeader>

    <div class="section-tip" style="margin-bottom: 16px">
      <strong>店铺名称</strong> 用于区分不同拼多多店（如 store_A、store_B）。
      <strong>登录账号</strong> 填拼多多商家后台的手机号或账号名。
      <strong>默认商品</strong> 在上架时会自动选中。
    </div>

    <el-card shadow="never" class="stat-card">
      <el-table :data="accounts" stripe>
        <el-table-column prop="account_id" label="店铺名称" width="120" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '使用中' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="username" label="登录账号" min-width="140" />
        <el-table-column label="密码" width="90">
          <template #default="{ row }">
            <el-tag :type="row.has_password ? 'success' : 'warning'" size="small">
              {{ row.has_password ? '已设置' : '未设置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="默认商品" min-width="200">
          <template #default="{ row }">
            <el-tag
              v-for="c in row.product_codes.slice(0, 4)"
              :key="c"
              size="small"
              style="margin: 0 4px 4px 0"
            >
              {{ c }}
            </el-tag>
            <span v-if="row.product_codes.length > 4" class="muted">+{{ row.product_codes.length - 4 }}</span>
            <span v-if="!row.product_codes.length" class="muted">未设置</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!accounts.length" description="还没有店铺，点击右上角添加" />
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? `编辑店铺 · ${form.account_id}` : '添加新店铺'"
      width="480px"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item v-if="!isEdit" label="店铺名称" required>
          <el-input v-model="form.account_id" placeholder="例如：store_A（方便自己识别即可）" />
        </el-form-item>

        <el-form-item label="是否启用">
          <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>

        <el-form-item label="拼多多登录账号">
          <el-input v-model="form.username" placeholder="手机号或账号名" />
        </el-form-item>

        <el-form-item :label="isEdit ? '登录密码（不修改请留空）' : '登录密码'">
          <el-input v-model="form.password" type="password" show-password />
        </el-form-item>

        <el-form-item label="默认上架商品">
          <el-select
            v-model="form.product_codes"
            multiple
            filterable
            allow-create
            style="width: 100%"
            placeholder="选择商品编码"
          >
            <el-option v-for="c in productOptions" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.muted {
  font-size: 12px;
  color: var(--text-muted);
}
</style>
