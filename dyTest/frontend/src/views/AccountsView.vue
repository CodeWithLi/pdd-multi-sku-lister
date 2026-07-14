<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import { loginModeLabel } from '@/utils/labels'
import type { Account, AccountDetail, ListingTargetOption } from '@/types'

const router = useRouter()
const loading = ref(false)
const accounts = ref<Account[]>([])
const dialogVisible = ref(false)
const isEdit = ref(false)
const saving = ref(false)
const productOptions = ref<ListingTargetOption[]>([])

const form = reactive({
  account_id: '',
  enabled: true,
  phone: '',
  username: '',
  password: '',
  login_mode: 'sms',
  product_codes: [] as string[],
})

function filterValidProductCodes(codes: string[]) {
  const valid = new Set(productOptions.value.map((item) => item.selector))
  return (codes || []).filter((code) => valid.has(code))
}

async function load() {
  loading.value = true
  try {
    const [accs, prods] = await Promise.all([api.accounts(), api.listingTargets()])
    accounts.value = accs
    productOptions.value = prods
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.account_id = ''
  form.enabled = true
  form.phone = ''
  form.username = ''
  form.password = ''
  form.login_mode = 'sms'
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
    form.phone = detail.phone
    form.username = detail.username
    form.password = detail.password
    form.login_mode = detail.login_mode || 'sms'
    form.product_codes = filterValidProductCodes(detail.product_codes)
    dialogVisible.value = true
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!isEdit.value && !form.account_id.trim()) {
    ElMessage.warning('请填写店铺 ID')
    return
  }
  if (!form.phone.trim() && !form.username.trim()) {
    ElMessage.warning('请填写登录手机号')
    return
  }
  saving.value = true
  try {
    const payload = {
      enabled: form.enabled,
      phone: form.phone.trim(),
      username: form.username.trim() || form.phone.trim(),
      password: form.password,
      login_mode: form.login_mode,
      product_codes: form.product_codes,
    }
    if (isEdit.value) {
      await api.updateAccount(form.account_id, payload)
      ElMessage.success('已保存')
    } else {
      await api.createAccount({ account_id: form.account_id.trim(), ...payload })
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
    await ElMessageBox.confirm(`确定删除店铺「${row.account_id}」吗？`, '删除确认', { type: 'warning' })
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
    <PageHeader title="店铺设置" desc="配置抖店登录手机号，数据保存到 MySQL。登录 Session 通过「登录体检」管理。">
      <template #actions>
        <el-button @click="router.push('/login-health')">登录体检</el-button>
        <el-button type="primary" @click="openCreate">+ 添加店铺</el-button>
      </template>
    </PageHeader>

    <div class="section-tip">
      <strong>店铺 ID</strong> 用于区分不同抖店（如 store_A）。<strong>手机号</strong> 用于短信登录。
      添加店铺后，请到 <strong>登录体检</strong> 点击「打开登录窗口」完成首次短信验证码登录，Session 会保存到本地 Profile。
    </div>

    <el-card shadow="never" class="stat-card">
      <el-table :data="accounts" stripe>
        <el-table-column prop="account_id" label="店铺 ID" width="120" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '使用中' : '已停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="phone" label="手机号" min-width="120" />
        <el-table-column label="登录方式" width="110">
          <template #default="{ row }">{{ loginModeLabel[row.login_mode] || row.login_mode }}</template>
        </el-table-column>
        <el-table-column label="抖店名称" min-width="140">
          <template #default="{ row }">
            <span v-if="row.shop_display_name">{{ row.shop_display_name }}</span>
            <span v-else class="muted">登录后自动获取</span>
          </template>
        </el-table-column>
        <el-table-column label="默认商品" min-width="200">
          <template #default="{ row }">
            <el-tag v-for="c in row.product_codes.slice(0, 4)" :key="c" size="small" style="margin: 0 4px 4px 0">{{ c }}</el-tag>
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

    <el-dialog v-model="dialogVisible" :title="isEdit ? `编辑店铺 · ${form.account_id}` : '添加新店铺'" width="480px" destroy-on-close>
      <el-form label-position="top">
        <el-form-item v-if="!isEdit" label="店铺 ID" required>
          <el-input v-model="form.account_id" placeholder="例如：store_A" />
        </el-form-item>
        <el-form-item label="是否启用">
          <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>
        <el-form-item label="登录手机号" required>
          <el-input v-model="form.phone" placeholder="抖店登录手机号" />
        </el-form-item>
        <el-form-item label="登录方式">
          <el-radio-group v-model="form.login_mode">
            <el-radio value="sms">短信验证码（推荐）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="默认上架商品">
          <el-select v-model="form.product_codes" multiple filterable style="width: 100%" placeholder="选择套图/商品">
            <el-option
              v-for="item in productOptions"
              :key="item.selector"
              :label="`${item.selector}（${item.product_count}个商品）`"
              :value="item.selector"
            />
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
.muted { font-size: 12px; color: var(--text-muted); }
code { font-size: 12px; background: #f1f5f9; padding: 2px 6px; border-radius: 4px; }
</style>
