<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowDown,
  Connection,
  DataBoard,
  Shop,
  FolderOpened,
  Goods,
  DocumentCopy,
  Document,
  Discount,
  TrendCharts,
  Key,
  Setting,
  Warning,
  CircleClose,
  Brush,
  Grid,
  Timer,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'

interface NavItem {
  path: string
  label: string
  icon: Component
}

interface NavGroup {
  key: string
  label: string
  items: NavItem[]
}

const route = useRoute()
const router = useRouter()

const topItem: NavItem = { path: '/', label: '工作台', icon: DataBoard }
const pipelineItem: NavItem = { path: '/pipeline', label: '整合链路', icon: Connection }
const bottomItem: NavItem = { path: '/settings', label: '系统设置', icon: Setting }

const navGroups: NavGroup[] = [
  {
    key: 'ops',
    label: '日常操作',
    items: [
      { path: '/tasks', label: '上架 / 下架', icon: Goods },
      { path: '/campaign', label: '活动', icon: Discount },
      { path: '/traffic', label: '推广', icon: TrendCharts },
      { path: '/traffic-report-schedule', label: '投流日报定时', icon: Timer },
      { path: '/catalog', label: '素材检查', icon: FolderOpened },
    ],
  },
  {
    key: 'store',
    label: '店铺管理',
    items: [
      { path: '/accounts', label: '店铺设置', icon: Shop },
      { path: '/login-health', label: '登录体检', icon: Key },
    ],
  },
  {
    key: 'data',
    label: '商品数据',
    items: [
      { path: '/published-products', label: '已发布商品', icon: DocumentCopy },
      { path: '/style-colors', label: '款式颜色', icon: Brush },
      { path: '/feishu-bitable', label: '飞书多维表格', icon: Grid },
    ],
  },
  {
    key: 'monitor',
    label: '监控排错',
    items: [
      { path: '/failures', label: '失败项工作台', icon: Warning },
      { path: '/pipeline-issues', label: '链路报错', icon: CircleClose },
      { path: '/runs', label: '操作记录', icon: Document },
    ],
  },
]

const allItems = computed(() => [
  topItem,
  pipelineItem,
  ...navGroups.flatMap((g) => g.items),
  bottomItem,
])

const active = computed(() => {
  const p = route.path
  if (p === '/') return '/'
  const item = allItems.value.find((m) => m.path !== '/' && p.startsWith(m.path))
  return item?.path ?? p
})

function groupHasActive(group: NavGroup) {
  return group.items.some((item) => active.value === item.path)
}

function loadOpenGroups(): string[] {
  try {
    const raw = sessionStorage.getItem('sidebar-open-groups')
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed
    }
  } catch {
    /* ignore */
  }
  return navGroups.map((g) => g.key)
}

const openGroups = ref<string[]>(loadOpenGroups())

function persistOpenGroups() {
  sessionStorage.setItem('sidebar-open-groups', JSON.stringify(openGroups.value))
}

function isGroupOpen(key: string) {
  return openGroups.value.includes(key)
}

function toggleGroup(key: string) {
  if (isGroupOpen(key)) {
    openGroups.value = openGroups.value.filter((k) => k !== key)
  } else {
    openGroups.value = [...openGroups.value, key]
  }
  persistOpenGroups()
}

function ensureActiveGroupOpen() {
  const group = navGroups.find((g) => groupHasActive(g))
  if (group && !isGroupOpen(group.key)) {
    openGroups.value = [...openGroups.value, group.key]
    persistOpenGroups()
  }
}

watch(
  () => route.path,
  () => ensureActiveGroupOpen(),
  { immediate: true },
)

function go(path: string) {
  router.push(path)
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="sidebar">
      <div class="brand">
        <div class="brand-icon">拼</div>
        <div class="brand-text">
          <div class="brand-title">拼多多上架助手</div>
          <div class="brand-sub">多规格商品 · 自动上架</div>
        </div>
      </div>

      <nav class="nav">
        <button
          class="nav-item top-item"
          :class="{ active: active === topItem.path }"
          @click="go(topItem.path)"
        >
          <el-icon class="nav-icon"><component :is="topItem.icon" /></el-icon>
          <span class="nav-label">{{ topItem.label }}</span>
        </button>

        <button
          class="nav-item pipeline-item"
          :class="{ active: active === pipelineItem.path }"
          @click="go(pipelineItem.path)"
        >
          <el-icon class="nav-icon"><component :is="pipelineItem.icon" /></el-icon>
          <span class="nav-label">{{ pipelineItem.label }}</span>
        </button>

        <section v-for="group in navGroups" :key="group.key" class="nav-group">
          <button class="group-head" @click="toggleGroup(group.key)">
            <span class="group-title">{{ group.label }}</span>
            <el-icon class="group-arrow" :class="{ open: isGroupOpen(group.key) }">
              <ArrowDown />
            </el-icon>
          </button>

          <div v-show="isGroupOpen(group.key)" class="group-items">
            <button
              v-for="item in group.items"
              :key="item.path"
              class="nav-item"
              :class="{ active: active === item.path }"
              @click="go(item.path)"
            >
              <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
              <span class="nav-label">{{ item.label }}</span>
            </button>
          </div>
        </section>
      </nav>

      <div class="sidebar-bottom">
        <button
          class="nav-item bottom-item"
          :class="{ active: active === bottomItem.path }"
          @click="go(bottomItem.path)"
        >
          <el-icon class="nav-icon"><component :is="bottomItem.icon" /></el-icon>
          <span class="nav-label">{{ bottomItem.label }}</span>
        </button>
        <div class="sidebar-foot">
          <el-icon><Setting /></el-icon>
          <span>有问题请联系技术同事</span>
        </div>
      </div>
    </el-aside>

    <el-main class="main">
      <router-view />
    </el-main>
  </el-container>
</template>

<style scoped>
.layout {
  min-height: 100vh;
  width: 100%;
  background: var(--app-bg);
}

.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 200;
  height: 100vh;
  background: var(--sidebar-bg);
  color: var(--sidebar-text);
  display: flex;
  flex-direction: column;
  padding: 16px 10px;
  overflow: hidden;
}

.brand {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 4px 8px 16px;
  flex-shrink: 0;
}

.brand-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: linear-gradient(135deg, #ff6b35, #ff8f5a);
  color: #fff;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 17px;
  box-shadow: 0 4px 12px rgba(255, 107, 53, 0.35);
  flex-shrink: 0;
}

.brand-text {
  min-width: 0;
}

.brand-title {
  color: #f8fafc;
  font-weight: 700;
  font-size: 14px;
  line-height: 1.3;
}

.brand-sub {
  font-size: 10px;
  color: #64748b;
  margin-top: 2px;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.nav::-webkit-scrollbar {
  width: 4px;
}

.nav::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.12);
  border-radius: 4px;
}

.nav-group {
  margin-top: 4px;
}

.group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  border: none;
  background: transparent;
  color: #64748b;
  padding: 6px 10px;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
  transition: color 0.15s;
}

.group-head:hover {
  color: #94a3b8;
}

.group-title {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.group-arrow {
  font-size: 12px;
  transition: transform 0.2s;
}

.group-arrow.open {
  transform: rotate(180deg);
}

.group-items {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  border: none;
  background: transparent;
  color: var(--sidebar-text);
  padding: 8px 10px 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
}

.group-items .nav-item {
  padding-left: 18px;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #e2e8f0;
}

.nav-item.active {
  background: var(--sidebar-active-bg);
  color: var(--sidebar-active);
}

.top-item {
  margin-bottom: 4px;
}

.nav-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.nav-label {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar-bottom {
  flex-shrink: 0;
  padding-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.bottom-item {
  margin-bottom: 4px;
}

.sidebar-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  color: #64748b;
  padding: 6px 10px 0;
}

.main {
  flex: 1;
  width: calc(100% - 220px);
  min-width: 0;
  margin-left: 220px;
  padding: 28px 32px 48px;
  overflow-x: clip;
  background:
    radial-gradient(circle at 78% 12%, rgba(255, 107, 53, 0.08), transparent 28%),
    linear-gradient(180deg, #f8fafc 0%, var(--app-bg) 42%, #eef3f9 100%);
}

@media (max-width: 768px) {
  .sidebar {
    width: 64px !important;
    padding: 12px 8px;
  }

  .brand {
    justify-content: center;
    padding: 4px 0 12px;
  }

  .brand-text,
  .group-head,
  .nav-label,
  .sidebar-foot span {
    display: none;
  }

  .group-items .nav-item,
  .nav-item {
    justify-content: center;
    padding: 10px;
  }

  .main {
    width: calc(100% - 64px);
    margin-left: 64px;
    padding: 20px 16px 32px;
  }
}
</style>
