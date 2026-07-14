<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type { Account, ConfigSummary, HealthResponse } from '@/types'

const router = useRouter()
const loading = ref(true)
const error = ref('')
const health = ref<HealthResponse | null>(null)
const summary = ref<ConfigSummary | null>(null)
const accounts = ref<Account[]>([])

const steps = [
  { title: '配置店铺', desc: '填写手机号、登录方式与默认商品', path: '/accounts' },
  { title: '检查素材', desc: '确认主图、Excel、SKU 是否齐全', path: '/catalog' },
  { title: '执行上架', desc: '选店铺和商品，自动发布到抖店', path: '/tasks' },
  { title: '查看记录', desc: '确认 Step1 是否完成', path: '/runs' },
]

const actions = [
  { icon: '📋', bg: '#fff0f3', title: '检查素材', desc: '上架前检查主图与 SKU', path: '/catalog' },
  { icon: '🚀', bg: '#ecfdf5', title: '商品上架', desc: '选择店铺和商品编码，自动发布', path: '/tasks' },
  { icon: '🏪', bg: '#eff6ff', title: '店铺设置', desc: '管理手机号、登录方式、默认商品', path: '/accounts' },
  { icon: '⚙️', bg: '#eef2ff', title: '系统设置', desc: '维护路径、浏览器和上架规则', path: '/settings' },
]

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [h, s, a] = await Promise.all([api.health(), api.configSummary(), api.accounts()])
    health.value = h
    summary.value = s
    accounts.value = a
  } catch (e) {
    error.value = e instanceof Error ? e.message : '无法连接后台服务'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="工作台" desc="先配店铺 → 查素材 → 上架 → 看记录" />

    <el-alert v-if="error" type="error" show-icon style="margin-bottom: 16px">
      <template #title>系统未启动</template>
      <template #default>
        请启动后台：<code>python -m dy_agent.main api --port 8020</code>
        <el-button link type="primary" @click="load">重新连接</el-button>
      </template>
    </el-alert>

    <el-alert
      v-else-if="health?.status === 'ok'"
      type="success"
      :closable="false"
      show-icon
      style="margin-bottom: 20px"
    >
      <template #title>系统运行正常</template>
      <template #default>
        已启用 {{ summary?.enabled_account_count ?? 0 }} 个店铺
        <span v-if="summary?.database_configured">
          · MySQL {{ summary.database_available ? '已连接' : '未连接' }}
        </span>
      </template>
    </el-alert>

    <div class="section-label">推荐操作流程</div>
    <div class="workflow-steps">
      <div v-for="(s, i) in steps" :key="s.path" class="workflow-step" @click="router.push(s.path)">
        <div class="num">{{ i + 1 }}</div>
        <div class="title">{{ s.title }}</div>
        <div class="desc">{{ s.desc }}</div>
      </div>
    </div>

    <div class="section-label">快捷入口</div>
    <div class="action-grid">
      <div v-for="a in actions" :key="a.title" class="action-card" @click="router.push(a.path)">
        <div class="icon" :style="{ background: a.bg }">{{ a.icon }}</div>
        <h3>{{ a.title }}</h3>
        <p>{{ a.desc }}</p>
      </div>
    </div>

    <el-card shadow="never" class="stat-card">
      <template #header>
        <div class="card-head">
          <span>我的店铺</span>
          <el-button type="primary" size="small" @click="router.push('/accounts')">管理店铺</el-button>
        </div>
      </template>
      <el-empty v-if="!accounts.length" description="还没有配置店铺">
        <el-button type="primary" @click="router.push('/accounts')">去添加第一个店铺</el-button>
      </el-empty>
      <div v-else class="shop-grid">
        <div v-for="acc in accounts" :key="acc.account_id" class="shop-card" :class="{ off: !acc.enabled }">
          <div class="shop-head">
            <span class="shop-name">{{ acc.account_id }}</span>
            <el-tag size="small" :type="acc.enabled ? 'success' : 'info'">{{ acc.enabled ? '使用中' : '已停用' }}</el-tag>
          </div>
          <div class="shop-line">手机号：{{ acc.phone || acc.username || '未填写' }}</div>
          <div class="shop-line">登录：{{ acc.login_mode === 'sms' ? '短信验证码' : acc.login_mode }}</div>
          <div class="shop-line">
            默认商品：
            <template v-if="acc.product_codes.length">{{ acc.product_codes.slice(0, 3).join('、') }}</template>
            <span v-else class="muted">未设置</span>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.section-label { font-size: 13px; font-weight: 600; color: #475569; margin-bottom: 12px; }
.card-head { display: flex; justify-content: space-between; align-items: center; }
.shop-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.shop-card { border: 1px solid var(--border-color); border-radius: 12px; padding: 14px; background: #fafbfc; }
.shop-card.off { opacity: 0.6; }
.shop-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.shop-name { font-weight: 700; font-size: 15px; }
.shop-line { font-size: 13px; color: var(--text-secondary); margin-bottom: 4px; }
</style>
