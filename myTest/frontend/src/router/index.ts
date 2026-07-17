import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '工作台' } },
    { path: '/daily-stats', name: 'daily-stats', component: () => import('@/views/DailyStatsView.vue'), meta: { title: '每日统计' } },
    { path: '/pipeline', name: 'pipeline', component: () => import('@/views/PipelineView.vue'), meta: { title: '整合链路' } },
    { path: '/submit-ai-title-config', name: 'submit-ai-title-config', component: () => import('@/views/SubmitAiTitleConfigView.vue'), meta: { title: 'AI 标题配置' } },
    { path: '/tasks', name: 'tasks', component: () => import('@/views/TasksView.vue'), meta: { title: '上架 / 下架' } },
    { path: '/campaign', name: 'campaign', component: () => import('@/views/CampaignView.vue'), meta: { title: '活动' } },
    { path: '/traffic', name: 'traffic', component: () => import('@/views/TrafficView.vue'), meta: { title: '推广' } },
    { path: '/traffic-report-schedule', name: 'traffic-report-schedule', component: () => import('@/views/TrafficReportScheduleView.vue'), meta: { title: '投流日报定时' } },
    { path: '/inventory-delist', name: 'inventory-delist', component: () => import('@/views/InventoryDelistView.vue'), meta: { title: '负库存下架' } },
    { path: '/product-operations', name: 'product-operations', component: () => import('@/views/ProductOperationsView.vue'), meta: { title: '商品操作' } },
    { path: '/catalog', name: 'catalog', component: () => import('@/views/CatalogView.vue'), meta: { title: '素材检查' } },
    { path: '/accounts', name: 'accounts', component: () => import('@/views/AccountsView.vue'), meta: { title: '店铺设置' } },
    { path: '/login-health', name: 'login-health', component: () => import('@/views/LoginHealthView.vue'), meta: { title: '登录体检' } },
    { path: '/published-products', name: 'published-products', component: () => import('@/views/PublishedProductsView.vue'), meta: { title: '已发布商品' } },
    { path: '/style-colors', name: 'style-colors', component: () => import('@/views/StyleColorsView.vue'), meta: { title: '款式颜色' } },
    { path: '/listing-product-attributes', name: 'listing-product-attributes', component: () => import('@/views/ListingProductAttributesView.vue'), meta: { title: '商品属性' } },
    { path: '/feishu/oauth/callback', name: 'feishu-oauth-callback', component: () => import('@/views/FeishuOAuthCallbackView.vue'), meta: { title: '飞书授权' } },
    { path: '/feishu-bitable', name: 'feishu-bitable', component: () => import('@/views/FeishuBitableView.vue'), meta: { title: '飞书多维表格' } },
    { path: '/failures', name: 'failures', component: () => import('@/views/FailuresView.vue'), meta: { title: '失败项工作台' } },
    { path: '/pdd-failure-logs', name: 'pdd-failure-logs', component: () => import('@/views/PddFailureLogView.vue'), meta: { title: '发布失败日志' } },
    { path: '/wecom-notify', name: 'wecom-notify', component: () => import('@/views/WecomNotifyView.vue'), meta: { title: '企业微信通知' } },
    { path: '/pipeline-issues', name: 'pipeline-issues', component: () => import('@/views/PipelineIssueReportsView.vue'), meta: { title: '链路报错' } },
    { path: '/settings', name: 'settings', component: () => import('@/views/SystemSettingsView.vue'), meta: { title: '系统设置' } },
    { path: '/runs', name: 'runs', component: () => import('@/views/RunsView.vue'), meta: { title: '操作记录' } },
  ],
})

router.afterEach((to) => {
  const page = (to.meta.title as string) || '拼多多上架助手'
  document.title = `${page} · 拼多多上架助手`
})

export default router
