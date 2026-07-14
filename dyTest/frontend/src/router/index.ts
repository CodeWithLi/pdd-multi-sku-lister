import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('@/views/DashboardView.vue'), meta: { title: '工作台' } },
    { path: '/accounts', component: () => import('@/views/AccountsView.vue'), meta: { title: '店铺设置' } },
    { path: '/login-health', component: () => import('@/views/LoginHealthView.vue'), meta: { title: '登录体检' } },
    { path: '/tasks', component: () => import('@/views/TasksView.vue'), meta: { title: '商品上架' } },
    { path: '/catalog', component: () => import('@/views/CatalogView.vue'), meta: { title: '素材检查' } },
    { path: '/runs', component: () => import('@/views/RunsView.vue'), meta: { title: '操作记录' } },
    { path: '/settings', component: () => import('@/views/SystemSettingsView.vue'), meta: { title: '系统设置' } },
    {
      path: '/feishu/oauth/callback',
      component: () => import('@/views/FeishuOAuthCallbackView.vue'),
      meta: { title: '飞书授权' },
    },
  ],
})

router.afterEach((to) => {
  document.title = `${(to.meta.title as string) || '抖店上架助手'} · 抖店上架助手`
})

export default router
