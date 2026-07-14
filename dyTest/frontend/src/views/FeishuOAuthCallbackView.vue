<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { completeFeishuOAuthCallback } from '@/composables/useFeishuAuth'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const message = ref('正在完成飞书授权…')
const ok = ref(false)

onMounted(async () => {
  try {
    const result = await completeFeishuOAuthCallback(router, route.query)
    ok.value = result.ok
    message.value = result.message
    if (!result.ok) loading.value = false
  } catch (e) {
    ok.value = false
    message.value = e instanceof Error ? e.message : '飞书授权失败'
    loading.value = false
  }
})

function backHome() {
  router.replace('/')
}
</script>

<template>
  <div v-loading="loading" class="oauth-page">
    <el-card shadow="never" class="oauth-card">
      <h2>飞书授权</h2>
      <el-result
        :icon="ok ? 'success' : loading ? 'info' : 'error'"
        :title="ok ? '授权成功' : loading ? '处理中' : '授权失败'"
        :sub-title="message"
      >
        <template v-if="!loading && !ok" #extra>
          <el-button type="primary" @click="backHome">返回继续操作</el-button>
        </template>
      </el-result>
    </el-card>
  </div>
</template>

<style scoped>
.oauth-page {
  min-height: 60vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.oauth-card {
  width: min(480px, 100%);
}
.oauth-card h2 {
  margin: 0 0 8px;
  font-size: 18px;
}
</style>
