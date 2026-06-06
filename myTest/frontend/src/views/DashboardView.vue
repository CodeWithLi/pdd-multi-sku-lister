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
  { title: '配置店铺', desc: '填写拼多多账号和默认商品', path: '/accounts' },
  { title: '检查素材', desc: '确认图片、Excel、SKU 齐全', path: '/catalog' },
  { title: '执行上架', desc: '选店铺和商品，一键发布', path: '/tasks' },
  { title: '查看记录', desc: '确认是否上架成功', path: '/runs' },
]

const actions = [
  {
    icon: '📋',
    bg: '#fff4ef',
    title: '检查素材',
    desc: '上架前检查主图、详情图、SKU 是否齐全',
    path: '/catalog',
  },
  {
    icon: '🚀',
    bg: '#ecfdf5',
    title: '商品上架',
    desc: '选择店铺和商品编码，自动发布到拼多多',
    path: '/tasks',
  },
  {
    icon: '📦',
    bg: '#fef3c7',
    title: '商品下架',
    desc: '按时间规则扫描并下架在售商品',
    path: '/tasks?tab=delist',
  },
  {
    icon: '🏪',
    bg: '#eff6ff',
    title: '店铺设置',
    desc: '管理店铺账号、密码、默认商品',
    path: '/accounts',
  },
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
    <PageHeader
      title="工作台"
      desc="按下面步骤操作即可：先配店铺 → 查素材 → 上架或下架 → 看记录"
    />

    <el-alert v-if="error" type="error" show-icon style="margin-bottom: 16px">
      <template #title>系统未启动</template>
      <template #default>
        请联系技术同事启动后台服务，或点击
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
        已启用 {{ summary?.enabled_account_count ?? 0 }} 个店铺，可以直接开始操作
      </template>
    </el-alert>

    <div class="section-label">推荐操作流程</div>
    <div class="workflow-steps">
      <div
        v-for="(s, i) in steps"
        :key="s.path"
        class="workflow-step"
        @click="router.push(s.path)"
      >
        <div class="num">{{ i + 1 }}</div>
        <div class="title">{{ s.title }}</div>
        <div class="desc">{{ s.desc }}</div>
      </div>
    </div>

    <div class="section-label">快捷入口</div>
    <el-row :gutter="16" style="margin-bottom: 24px">
      <el-col v-for="a in actions" :key="a.title" :span="6">
        <div class="action-card" @click="router.push(a.path)">
          <div class="icon" :style="{ background: a.bg }">{{ a.icon }}</div>
          <h3>{{ a.title }}</h3>
          <p>{{ a.desc }}</p>
        </div>
      </el-col>
    </el-row>

    <el-card shadow="never" class="stat-card">
      <template #header>
        <div class="card-head">
          <span>我的店铺</span>
          <el-button type="primary" size="small" @click="router.push('/accounts')">
            管理店铺
          </el-button>
        </div>
      </template>

      <el-empty v-if="!accounts.length" description="还没有配置店铺">
        <el-button type="primary" @click="router.push('/accounts')">去添加第一个店铺</el-button>
      </el-empty>

      <el-row v-else :gutter="12">
        <el-col v-for="acc in accounts" :key="acc.account_id" :span="8">
          <div class="shop-card" :class="{ off: !acc.enabled }">
            <div class="shop-head">
              <span class="shop-name">{{ acc.account_id }}</span>
              <el-tag size="small" :type="acc.enabled ? 'success' : 'info'">
                {{ acc.enabled ? '使用中' : '已停用' }}
              </el-tag>
            </div>
            <div class="shop-line">登录账号：{{ acc.username || '未填写' }}</div>
            <div class="shop-line">
              默认商品：
              <template v-if="acc.product_codes.length">
                {{ acc.product_codes.slice(0, 3).join('、') }}
                <span v-if="acc.product_codes.length > 3">等{{ acc.product_codes.length }}个</span>
              </template>
              <span v-else class="muted">未设置</span>
            </div>
          </div>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>

<style scoped>
.section-label {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 12px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.workflow-step {
  cursor: pointer;
  transition: border-color 0.15s;
}

.workflow-step:hover {
  border-color: #ffb899;
}

.shop-card {
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 14px;
  background: #fafbfc;
  margin-bottom: 12px;
}

.shop-card.off {
  opacity: 0.6;
}

.shop-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.shop-name {
  font-weight: 700;
  font-size: 15px;
}

.shop-line {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.muted {
  color: var(--text-muted);
}
</style>
