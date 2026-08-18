<template>
  <div>
    <!-- 欢迎区域 -->
    <div class="welcome-section">
      <div class="welcome-content">
        <h1 class="welcome-title">欢迎使用晨阳云枢</h1>
        <p class="welcome-subtitle">统一管理 CyImagePro 的用户、订单、Token 与模型资源</p>
      </div>
      <div class="welcome-brand">
        <div class="brand-badge">CyCloudHub</div>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card" v-for="(s, i) in stats" :key="s.label">
        <div class="stat-card-icon" :style="{ background: statColors[i].bg, color: statColors[i].color }">
          <component :is="statIcons[i]" />
        </div>
        <div class="stat-card-content">
          <div class="stat-card-label">{{ s.label }}</div>
          <div class="stat-card-value">{{ s.value }}</div>
        </div>
      </div>
    </div>

    <!-- 快捷入口 -->
    <div class="quick-actions">
      <n-card class="quick-card" :bordered="true">
        <template #header>
          <div class="quick-card-header">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" style="color: var(--cy-primary)">
              <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 14l-5-5h3V8h4v4h3l-5 5z"/>
            </svg>
            <span>快捷入口</span>
          </div>
        </template>
        <div class="quick-actions-grid">
          <div class="quick-action-item" @click="$router.push('/tokens')">
            <div class="quick-action-icon" style="background: var(--cy-info-bg); color: var(--cy-info);">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M20 6h-4V4c0-1.1-.9-2-2-2h-4c-1.1 0-2 .9-2 2v2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-8-2h4v2h-4V4zM4 8h16v3H4V8zm0 12V13h5v2h6v-2h5v7H4z"/>
              </svg>
            </div>
            <div class="quick-action-label">Token 库存</div>
          </div>
          <div class="quick-action-item" @click="$router.push('/orders')">
            <div class="quick-action-icon" style="background: var(--cy-success-bg); color: var(--cy-success);">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M18 17H6v-2h12v2zm0-4H6v-2h12v2zm0-4H6V7h12v2zM3 22l1.5-1.5L6 22l1.5-1.5L9 22l1.5-1.5L12 22l1.5-1.5L15 22l1.5-1.5L18 22l1.5-1.5L21 22V2l-1.5 1.5L18 2l-1.5 1.5L15 2l-1.5 1.5L12 2l-1.5 1.5L9 2 7.5 3.5 6 2 4.5 3.5 3 2v20z"/>
              </svg>
            </div>
            <div class="quick-action-label">交易订单</div>
          </div>
          <div class="quick-action-item" @click="$router.push('/users')">
            <div class="quick-action-icon" style="background: var(--cy-warning-bg); color: var(--cy-warning);">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>
              </svg>
            </div>
            <div class="quick-action-label">客户账户</div>
          </div>
          <div class="quick-action-item" @click="$router.push('/settings')">
            <div class="quick-action-icon" style="background: var(--cy-primary-light); color: var(--cy-primary);">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 00.12-.61l-1.92-3.32a.49.49 0 00-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 00-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.07.62-.07.94s.02.64.07.94l-2.03 1.58a.49.49 0 00-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/>
              </svg>
            </div>
            <div class="quick-action-label">系统配置</div>
          </div>
        </div>
      </n-card>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, h, defineComponent } from 'vue'
import http from '../api/http'

const statColors = [
  { bg: '#E6FFFA', color: '#00BFA6' },      // 用户总数 - 青绿色
  { bg: '#EFF6FF', color: '#3B82F6' },      // 今日 Image2 调用 - 蓝色
  { bg: '#FEF3C7', color: '#F59E0B' },      // 累计充值 - 金黄色
  { bg: '#ECFDF5', color: '#10B981' },      // 可用 Token - 绿色
  { bg: '#FCE7F3', color: '#EC4899' },      // 试用 Token 可用 - 粉色
  { bg: '#EEF2FF', color: '#6366F1' },      // 在线设备 - 靛蓝
  { bg: '#FFF1F2', color: '#F43F5E' },      // 待审退款 - 玫红
]

// 统一线性风格图标 (stroke-based，更企业感)
const statIcons = [
  // 用户总数 - 用户群组图标
  defineComponent({
    render: () => h('svg', { width: 20, height: 20, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, [
      h('path', { d: 'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2' }),
      h('circle', { cx: 9, cy: 7, r: 4 }),
      h('path', { d: 'M23 21v-2a4 4 0 0 0-3-3.87' }),
      h('path', { d: 'M16 3.13a4 4 0 0 1 0 7.75' })
    ])
  }),
  // 今日 Image2 调用 - 图片/图像图标
  defineComponent({
    render: () => h('svg', { width: 20, height: 20, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, [
      h('rect', { x: 3, y: 3, width: 18, height: 18, rx: 2, ry: 2 }),
      h('circle', { cx: 8.5, cy: 8.5, r: 1.5 }),
      h('polyline', { points: '21 15 16 10 5 21' })
    ])
  }),
  // 累计充值 - 收据/订单单据图标
  defineComponent({
    render: () => h('svg', { width: 20, height: 20, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, [
      h('path', { d: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z' }),
      h('polyline', { points: '14 2 14 8 20 8' }),
      h('line', { x1: 16, y1: 13, x2: 8, y2: 13 }),
      h('line', { x1: 16, y1: 17, x2: 8, y2: 17 }),
      h('polyline', { points: '10 9 9 9 8 9' })
    ])
  }),
  // 可用 Token - 令牌图标
  defineComponent({
    render: () => h('svg', { width: 20, height: 20, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, [
      h('path', { d: 'M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4' })
    ])
  }),
  // 试用 Token - 礼物/赠送图标
  defineComponent({
    render: () => h('svg', { width: 20, height: 20, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, [
      h('polyline', { points: '20 12 20 22 4 22 4 12' }),
      h('rect', { x: 2, y: 7, width: 20, height: 5 }),
      h('line', { x1: 12, y1: 22, x2: 12, y2: 7 }),
      h('path', { d: 'M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z' }),
      h('path', { d: 'M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z' })
    ])
  }),
  // 在线设备 - 显示器图标
  defineComponent({
    render: () => h('svg', { width: 20, height: 20, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, [
      h('rect', { x: 2, y: 3, width: 20, height: 14, rx: 2, ry: 2 }),
      h('line', { x1: 8, y1: 21, x2: 16, y2: 21 }),
      h('line', { x1: 12, y1: 17, x2: 12, y2: 21 })
    ])
  }),
  // 待审退款 - 退还/循环图标
  defineComponent({
    render: () => h('svg', { width: 20, height: 20, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, [
      h('polyline', { points: '1 4 1 10 7 10' }),
      h('path', { d: 'M3.51 15a9 9 0 1 0 2.13-9.36L1 10' })
    ])
  }),
]

const stats = ref([
  { label: '用户总数', value: '-' },
  { label: '今日 Image2 调用', value: '-' },
  { label: '累计充值 (USD)', value: '-' },
  { label: '可用 Token', value: '-' },
  { label: '试用 Token 可用', value: '-' },
  { label: '在线设备', value: '-' },
  { label: '待审退款', value: '-' },
])

onMounted(async () => {
  try {
    const { data } = await http.get('/api/admin/stats')
    stats.value = [
      { label: '用户总数', value: data.users_total ?? '-' },
      { label: '今日 Image2 调用', value: data.image2_today ? `${data.image2_today.calls} 次 / ${data.image2_today.images} 张` : '-' },
      { label: '累计充值 (USD)', value: data.total_revenue_usd != null ? `$${Number(data.total_revenue_usd).toFixed(2)}` : '-' },
      { label: '可用 Token', value: data.token_stats ? data.token_stats.available : '-' },
      { label: '试用 Token 可用', value: data.token_stats ? data.token_stats.trial_available : '-' },
      { label: '在线设备', value: data.online_devices ?? '-' },
      { label: '待审退款', value: data.pending_refunds ?? '-' },
    ]
  } catch {}
})
</script>

<style scoped>
/* 欢迎区域 */
.welcome-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  padding: 28px 32px;
  background: linear-gradient(135deg, #00BFA6 0%, #0F766E 100%);
  border-radius: var(--cy-radius-xl);
  color: white;
}

.welcome-title {
  font-size: 24px;
  font-weight: 700;
  margin: 0 0 8px;
  letter-spacing: -0.02em;
}

.welcome-subtitle {
  font-size: 14px;
  opacity: 0.9;
  margin: 0;
}

.welcome-brand {
  display: flex;
  align-items: center;
}

.brand-badge {
  background: rgba(255, 255, 255, 0.2);
  padding: 8px 16px;
  border-radius: var(--cy-radius);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.05em;
  backdrop-filter: blur(4px);
}

/* 统计卡片网格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

@media (max-width: 1200px) {
  .stats-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .welcome-section {
    flex-direction: column;
    text-align: center;
    padding: 24px;
  }
  .welcome-brand {
    margin-top: 16px;
  }
}

@media (max-width: 480px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}

.stat-card {
  background: var(--cy-bg-elevated);
  border: 1px solid var(--cy-border);
  border-radius: var(--cy-radius-lg);
  padding: 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  transition: all 0.2s;
  min-height: 100px;
}

.stat-card:hover {
  border-color: var(--cy-border-dark);
  box-shadow: var(--cy-shadow-md);
}

.stat-card-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-card-content {
  flex: 1;
  min-width: 0;
}

.stat-card-label {
  font-size: 13px;
  color: var(--cy-text-muted);
  margin-bottom: 8px;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-card-value {
  font-family: var(--cy-font-mono);
  font-size: 32px;
  font-weight: 700;
  color: var(--cy-text);
  letter-spacing: -0.02em;
  line-height: 1;
}

/* 快捷入口 */
.quick-actions {
  margin-bottom: 24px;
}

.quick-card {
  background: var(--cy-bg-elevated) !important;
  border: 1px solid var(--cy-border) !important;
  border-radius: var(--cy-radius-lg) !important;
}

.quick-card :deep(.n-card-header) {
  padding: 16px 20px !important;
  border-bottom: 1px solid var(--cy-border-light);
}

.quick-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--cy-text);
}

.quick-card :deep(.n-card__content) {
  padding: 20px !important;
}

.quick-actions-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

@media (max-width: 768px) {
  .quick-actions-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.quick-action-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 20px;
  background: var(--cy-bg-muted);
  border-radius: var(--cy-radius-md);
  cursor: pointer;
  transition: all 0.2s;
}

.quick-action-item:hover {
  background: var(--cy-bg);
  box-shadow: var(--cy-shadow);
  transform: translateY(-2px);
}

.quick-action-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--cy-radius);
  display: flex;
  align-items: center;
  justify-content: center;
}

.quick-action-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--cy-text);
}
</style>
