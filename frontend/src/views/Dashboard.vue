<template>
  <div>
    <div class="page-header">
      <h2 class="page-header-title">概览</h2>
    </div>
    <n-grid :cols="5" :x-gap="16" :y-gap="16" responsive="screen" item-responsive>
      <n-gi v-for="(s, i) in stats" :key="s.label" span="0:5 800:1">
        <div class="stat-card">
          <div class="stat-card-accent" :style="{ background: accentColors[i] }"></div>
          <div class="stat-card-label">{{ s.label }}</div>
          <div class="stat-card-value">{{ s.value }}</div>
        </div>
      </n-gi>
    </n-grid>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import http from '../api/http'

const accentColors = [
  'linear-gradient(90deg, #00d4aa, #00d4aa00)',
  'linear-gradient(90deg, #6366f1, #6366f100)',
  'linear-gradient(90deg, #f59e0b, #f59e0b00)',
  'linear-gradient(90deg, #3b82f6, #3b82f600)',
  'linear-gradient(90deg, #ec4899, #ec489900)',
]

const stats = ref([
  { label: '用户总数', value: '-' },
  { label: '今日成功订单', value: '-' },
  { label: '图片 Token 库存', value: '-' },
  { label: '对话 Token 库存', value: '-' },
  { label: '试用 Token 库存', value: '-' },
])

onMounted(async () => {
  try {
    const [stock, users, orders] = await Promise.all([
      http.get('/api/admin/tokens/stock'),
      http.get('/api/admin/users'),
      http.get('/api/admin/orders'),
    ])
    const imageStock = Object.entries(stock.data.image || {})
      .filter(([k]) => k !== '1')
      .reduce((s, [, v]) => s + v, 0)
    const chatStock = Object.entries(stock.data.chat || {})
      .filter(([k]) => k !== '1')
      .reduce((s, [, v]) => s + v, 0)
    const trialStock = (stock.data.image || {})['1'] ?? 0
    const today = new Date().toISOString().slice(0, 10)
    const todayOrders = orders.data.filter(o => o.created_at.startsWith(today) && o.status === 'paid').length
    stats.value = [
      { label: '用户总数', value: users.data.length },
      { label: '今日成功订单', value: todayOrders },
      { label: '图片 Token 库存', value: imageStock },
      { label: '对话 Token 库存', value: chatStock },
      { label: '试用 Token 库存', value: trialStock },
    ]
  } catch {}
})
</script>