<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Link, Refresh } from '@element-plus/icons-vue'
import {
  fetchFeishuAuthStatus,
  startFeishuOAuth,
  type FeishuAuthDisplayStatus,
} from '@/composables/useFeishuAuth'

const route = useRoute()
const status = ref<FeishuAuthDisplayStatus>('loading')
const hint = ref('')
const authorizing = ref(false)

async function refreshStatus() {
  status.value = 'loading'
  try {
    const res = await fetchFeishuAuthStatus()
    if (res.authorized) {
      status.value = 'authorized'
      hint.value = res.message || '授权有效'
      return
    }
    if (res.need_oauth) {
      status.value = 'unauthorized'
      hint.value = '日志写飞书需授权'
      return
    }
    status.value = 'unknown'
    hint.value = res.message || '未检测'
  } catch (e) {
    status.value = 'unknown'
    hint.value = e instanceof Error ? e.message : '检测失败'
  }
}

async function authorize() {
  authorizing.value = true
  try {
    await startFeishuOAuth(route.fullPath)
  } catch (e) {
    authorizing.value = false
    ElMessage.error(e instanceof Error ? e.message : '无法打开飞书授权')
  }
}

onMounted(refreshStatus)

defineExpose({ refreshStatus })
</script>

<template>
  <div class="feishu-auth" :class="status">
    <div class="feishu-auth-row">
      <span class="feishu-dot" />
      <div class="feishu-auth-text">
        <div class="feishu-auth-title">飞书授权</div>
        <div class="feishu-auth-hint">{{ hint }}</div>
      </div>
      <button
        v-if="status === 'unauthorized'"
        class="feishu-auth-btn"
        type="button"
        :disabled="authorizing"
        @click="authorize"
      >
        <el-icon><Link /></el-icon>
        去授权
      </button>
      <button
        v-else-if="status !== 'loading'"
        class="feishu-auth-refresh"
        type="button"
        title="重新检测"
        @click="refreshStatus"
      >
        <el-icon><Refresh /></el-icon>
      </button>
    </div>
  </div>
</template>

<style scoped>
.feishu-auth {
  margin-bottom: 8px;
  padding: 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.feishu-auth-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.feishu-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: #64748b;
}

.feishu-auth.authorized .feishu-dot {
  background: #22c55e;
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.5);
}

.feishu-auth.unauthorized .feishu-dot {
  background: #f59e0b;
  box-shadow: 0 0 6px rgba(245, 158, 11, 0.45);
}

.feishu-auth-text {
  flex: 1;
  min-width: 0;
}

.feishu-auth-title {
  font-size: 12px;
  font-weight: 600;
  color: #e2e8f0;
  line-height: 1.3;
}

.feishu-auth-hint {
  font-size: 10px;
  color: #64748b;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.feishu-auth-btn {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(135deg, #3370ff, #5b8cff);
  cursor: pointer;
}

.feishu-auth-btn:hover:not(:disabled) {
  filter: brightness(1.08);
}

.feishu-auth-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.feishu-auth-refresh {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
}

.feishu-auth-refresh:hover {
  color: #94a3b8;
}
</style>
