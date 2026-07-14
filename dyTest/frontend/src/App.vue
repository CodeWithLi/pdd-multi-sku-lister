<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import FeishuSidebarAuth from '@/components/FeishuSidebarAuth.vue'
import { DataBoard, Shop, Goods, FolderOpened, Document, Setting, Key } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

const navItems = [
  { path: '/', label: '工作台', icon: DataBoard },
  { path: '/accounts', label: '店铺设置', icon: Shop },
  { path: '/login-health', label: '登录体检', icon: Key },
  { path: '/catalog', label: '素材检查', icon: FolderOpened },
  { path: '/tasks', label: '商品上架', icon: Goods },
  { path: '/runs', label: '操作记录', icon: Document },
  { path: '/settings', label: '系统设置', icon: Setting },
]

const active = computed(() => {
  const p = route.path
  if (p === '/') return '/'
  const item = navItems.find((m) => m.path !== '/' && p.startsWith(m.path))
  return item?.path ?? p
})
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="sidebar">
      <div class="brand">
        <div class="brand-icon">抖</div>
        <div>
          <div class="brand-title">抖店上架助手</div>
          <div class="brand-sub">多规格商品 · 自动上架</div>
        </div>
      </div>
      <nav class="nav">
        <button
          v-for="item in navItems"
          :key="item.path"
          class="nav-item"
          :class="{ active: active === item.path }"
          @click="router.push(item.path)"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </button>
      </nav>
      <div class="sidebar-bottom">
        <FeishuSidebarAuth />
      </div>
    </el-aside>
    <el-main class="main"><router-view /></el-main>
  </el-container>
</template>

<style scoped>
.layout { min-height: 100vh; background: var(--app-bg); }
.sidebar {
  position: fixed; top: 0; left: 0; height: 100vh; width: 220px;
  background: var(--sidebar-bg); color: var(--sidebar-text);
  display: flex; flex-direction: column; padding: 16px 10px;
}
.brand { display: flex; gap: 10px; align-items: center; padding: 4px 8px 16px; }
.brand-icon {
  width: 38px; height: 38px; border-radius: 10px;
  background: linear-gradient(135deg, #fe2c55, #ff6b8a);
  color: #fff; font-weight: 800; display: flex; align-items: center; justify-content: center;
}
.brand-title { color: #f8fafc; font-weight: 700; font-size: 14px; }
.brand-sub { font-size: 10px; color: #64748b; margin-top: 2px; }
.nav { display: flex; flex-direction: column; gap: 4px; }
.nav-item {
  display: flex; align-items: center; gap: 10px; width: 100%;
  border: none; background: transparent; color: var(--sidebar-text);
  padding: 10px 12px; border-radius: 8px; cursor: pointer; text-align: left;
}
.nav-item:hover { background: rgba(255,255,255,0.06); color: #e2e8f0; }
.nav-item.active { background: var(--sidebar-active-bg); color: var(--sidebar-active); }
.sidebar-bottom {
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.main {
  margin-left: 220px; width: calc(100% - 220px); min-width: 0;
  padding: 28px 32px 48px;
  background: linear-gradient(180deg, #f8fafc 0%, var(--app-bg) 42%, #eef3f9 100%);
}
</style>
