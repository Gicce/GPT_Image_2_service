<template>
  <div>
    <n-h2>概览</n-h2>
    <n-grid :cols="5" :x-gap="16" :y-gap="16">
      <n-gi v-for="s in stats" :key="s.label">
        <n-card>
          <n-statistic :label="s.label" :value="s.value" />
        </n-card>
      </n-gi>
    </n-grid>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import http from '../api/http'

const stats = ref([
  { label: '用户总数', value: '-' },
  { label: '今日订单', value: '-' },
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
