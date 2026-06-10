<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  DataBoard,
  Shop,
  FolderOpened,
  Goods,
  DocumentCopy,
  Document,
  Key,
  Setting,
  Warning,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

const menus = [
  { path: '/', label: '工作台', desc: '日常入口', icon: DataBoard },
  { path: '/tasks', label: '上架 / 下架', desc: '执行操作', icon: Goods },
  { path: '/catalog', label: '素材检查', desc: '上架前检查', icon: FolderOpened },
  { path: '/accounts', label: '店铺设置', desc: '账号管理', icon: Shop },
  { path: '/login-health', label: '登录体检', desc: '状态检查', icon: Key },
  { path: '/published-products', label: '已发布商品', desc: '商品ID映射', icon: DocumentCopy },
  { path: '/failures', label: '失败项工作台', desc: '人工重跑', icon: Warning },
  { path: '/settings', label: '系统设置', desc: '运行参数', icon: Setting },
  { path: '/runs', label: '操作记录', desc: '历史结果', icon: Document },
]

const active = computed(() => {
  const p = route.path
  if (p === '/') return '/'
  const item = menus.find((m) => m.path !== '/' && p.startsWith(m.path))
  return item?.path ?? p
})

function go(path: string) {
  router.push(path)
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="240px" class="sidebar">
      <div class="brand">
        <div class="brand-icon">拼</div>
        <div>
          <div class="brand-title">拼多多上架助手</div>
          <div class="brand-sub">多规格商品 · 自动上架</div>
        </div>
      </div>

      <nav class="nav">
        <button
          v-for="item in menus"
          :key="item.path"
          class="nav-item"
          :class="{ active: active === item.path }"
          @click="go(item.path)"
        >
          <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
          <div class="nav-text">
            <span class="nav-label">{{ item.label }}</span>
            <span class="nav-desc">{{ item.desc }}</span>
          </div>
        </button>
      </nav>

      <div class="sidebar-foot">
        <el-icon><Setting /></el-icon>
        <span>有问题请联系技术同事</span>
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
  background: var(--sidebar-bg);
  color: var(--sidebar-text);
  display: flex;
  flex-direction: column;
  padding: 20px 12px;
}

.brand {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 8px 10px 28px;
}

.brand-icon {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: linear-gradient(135deg, #ff6b35, #ff8f5a);
  color: #fff;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  box-shadow: 0 4px 12px rgba(255, 107, 53, 0.35);
}

.brand-title {
  color: #f8fafc;
  font-weight: 700;
  font-size: 15px;
}

.brand-sub {
  font-size: 11px;
  color: #64748b;
  margin-top: 3px;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  border: none;
  background: transparent;
  color: var(--sidebar-text);
  padding: 11px 12px;
  border-radius: 10px;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #e2e8f0;
}

.nav-item.active {
  background: var(--sidebar-active-bg);
  color: var(--sidebar-active);
}

.nav-icon {
  font-size: 18px;
  flex-shrink: 0;
}

.nav-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-label {
  font-size: 14px;
  font-weight: 600;
}

.nav-desc {
  font-size: 11px;
  opacity: 0.65;
}

.sidebar-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #64748b;
  padding: 14px 10px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.main {
  flex: 1;
  width: 100%;
  min-width: 0;
  padding: 28px 32px 48px;
  overflow-x: hidden;
  background:
    radial-gradient(circle at 78% 12%, rgba(255, 107, 53, 0.08), transparent 28%),
    linear-gradient(180deg, #f8fafc 0%, var(--app-bg) 42%, #eef3f9 100%);
}

@media (max-width: 768px) {
  .sidebar {
    width: 78px !important;
    padding: 16px 10px;
  }

  .brand {
    justify-content: center;
    padding: 4px 0 20px;
  }

  .brand > div:not(.brand-icon),
  .nav-text,
  .sidebar-foot span {
    display: none;
  }

  .nav-item {
    justify-content: center;
    padding: 12px;
  }

  .main {
    padding: 20px 16px 32px;
  }
}
</style>
