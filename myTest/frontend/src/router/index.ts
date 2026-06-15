import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '工作台' } },
    { path: '/pipeline', name: 'pipeline', component: () => import('@/views/PipelineView.vue'), meta: { title: '整合链路' } },
    { path: '/tasks', name: 'tasks', component: () => import('@/views/TasksView.vue'), meta: { title: '上架 / 下架' } },
    { path: '/campaign', name: 'campaign', component: () => import('@/views/CampaignView.vue'), meta: { title: '活动' } },
    { path: '/traffic', name: 'traffic', component: () => import('@/views/TrafficView.vue'), meta: { title: '推广' } },
    { path: '/catalog', name: 'catalog', component: () => import('@/views/CatalogView.vue'), meta: { title: '素材检查' } },
    { path: '/accounts', name: 'accounts', component: () => import('@/views/AccountsView.vue'), meta: { title: '店铺设置' } },
    { path: '/login-health', name: 'login-health', component: () => import('@/views/LoginHealthView.vue'), meta: { title: '登录体检' } },
    { path: '/published-products', name: 'published-products', component: () => import('@/views/PublishedProductsView.vue'), meta: { title: '已发布商品' } },
    { path: '/style-colors', name: 'style-colors', component: () => import('@/views/StyleColorsView.vue'), meta: { title: '款式颜色' } },
    { path: '/failures', name: 'failures', component: () => import('@/views/FailuresView.vue'), meta: { title: '失败项工作台' } },
    { path: '/settings', name: 'settings', component: () => import('@/views/SystemSettingsView.vue'), meta: { title: '系统设置' } },
    { path: '/runs', name: 'runs', component: () => import('@/views/RunsView.vue'), meta: { title: '操作记录' } },
  ],
})

router.afterEach((to) => {
  const page = (to.meta.title as string) || '拼多多上架助手'
  document.title = `${page} · 拼多多上架助手`
})

export default router
