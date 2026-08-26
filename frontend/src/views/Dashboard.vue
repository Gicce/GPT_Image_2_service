<template>
  <div class="dashboard-page">
    <div class="page-header dashboard-header">
      <div class="page-header-left">
        <h2 class="page-header-title">运营概览</h2>
        <p class="page-header-subtitle">客户、Image2 用量、充值点数与服务状态</p>
      </div>
      <n-button size="small" :loading="loading" @click="loadStats">刷新数据</n-button>
    </div>

    <div class="stats-grid">
      <div v-for="stat in stats" :key="stat.key" class="overview-card">
        <div class="overview-icon" :style="{ background: stat.bg, color: stat.color }">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
            <path :d="stat.icon" />
          </svg>
        </div>
        <div class="overview-content">
          <div class="overview-label">{{ stat.label }}</div>
          <div class="overview-value" :class="{ compact: stat.compact }">{{ stat.value }}</div>
          <div v-if="stat.note" class="overview-note">{{ stat.note }}</div>
        </div>
      </div>
    </div>

    <n-alert v-if="loadError" type="error" :bordered="false">
      {{ loadError }}
    </n-alert>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import http from '../api/http'

const loading = ref(false)
const loadError = ref('')
const data = ref({})

const icons = {
  users: 'M16 11c1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3 1.34 3 3 3zM8 11c1.66 0 3-1.34 3-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.34 0-7 1.17-7 3.5V19h14v-2.5C15 14.17 10.34 13 8 13zm8 0c-.29 0-.62.02-.97.05 1.17.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.66-3.5-7-3.5z',
  image: 'M21 19V5c0-1.1-.9-2-2-2H5C3.9 3 3 3.9 3 5v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 11.5l2.5 3.01L14.5 10l4.5 6H5l3.5-4.5z',
  credits: 'M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm1 17h-2v-1.25c-1.38-.3-2.5-1.17-2.5-2.75h2c0 .83.67 1.25 1.5 1.25s1.5-.42 1.5-1.25c0-.73-.45-1.03-1.83-1.36C9.75 12.18 8.5 11.43 8.5 9.75c0-1.4 1.04-2.42 2.5-2.71V6h2v1.04c1.46.29 2.5 1.31 2.5 2.71h-2c0-.74-.67-1.15-1.5-1.15s-1.5.41-1.5 1.15c0 .67.56.94 1.83 1.25 1.91.46 3.17 1.25 3.17 3 0 1.58-1.12 2.45-2.5 2.75V18z',
  device: 'M4 6h18V4H4c-1.1 0-2 .9-2 2v11H0v3h14v-3H4V6zm19 2h-6c-.55 0-1 .45-1 1v12c0 .55.45 1 1 1h6c.55 0 1-.45 1-1V9c0-.55-.45-1-1-1zm-1 12h-4V10h4v10z',
  refund: 'M7.34 6.41L.86 12.9l6.49 6.48 1.41-1.41-4.08-4.07H17v-2H4.68l4.07-4.08-1.41-1.41zM16.66 4.62l-1.41 1.41 4.08 4.07H7v2h12.32l-4.07 4.08 1.41 1.41 6.48-6.49-6.48-6.48z',
}

const stats = computed(() => {
  const today = data.value.image2_today || {}
  return [
    { key: 'users', label: '客户总数', value: data.value.users_total ?? '-', icon: icons.users, bg: '#e6fffa', color: '#00a890' },
    { key: 'image2', label: '今日 Image2', value: `${today.calls ?? 0} 次`, note: `${today.images ?? 0} 张图片`, compact: true, icon: icons.image, bg: '#eff6ff', color: '#3b82f6' },
    { key: 'credits', label: '累计充值点数', value: Number(data.value.total_recharged_credits ?? 0).toLocaleString('zh-CN'), icon: icons.credits, bg: '#fffbeb', color: '#f59e0b' },
    { key: 'devices', label: '在线设备', value: data.value.online_devices ?? '-', icon: icons.device, bg: '#eef2ff', color: '#6366f1' },
    { key: 'refunds', label: '待审退款', value: data.value.pending_refunds ?? '-', icon: icons.refund, bg: '#fef2f2', color: '#ef4444' },
  ]
})

async function loadStats() {
  loading.value = true
  loadError.value = ''
  try {
    const response = await http.get('/api/admin/stats')
    data.value = response.data
  } catch (error) {
    loadError.value = error.response?.data?.detail || '概览数据加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

onMounted(loadStats)
</script>

<style scoped>
.dashboard-page { min-width: 0; }
.dashboard-header { align-items: center; }
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}
.overview-card {
  min-width: 0;
  min-height: 132px;
  padding: 22px;
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--cy-bg-elevated);
  border: 1px solid var(--cy-border);
  border-radius: var(--cy-radius-lg);
}
.overview-icon {
  width: 46px;
  height: 46px;
  flex: 0 0 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.overview-content { min-width: 0; }
.overview-label { margin-bottom: 6px; color: var(--cy-text-muted); font-size: 13px; }
.overview-value {
  color: var(--cy-text);
  font: 700 30px/1.15 var(--cy-font-mono);
  overflow-wrap: anywhere;
}
.overview-value.compact { font-size: 25px; }
.overview-note { margin-top: 4px; color: var(--cy-text-muted); font-size: 12px; }
@media (max-width: 1199px) {
  .stats-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
</style>
