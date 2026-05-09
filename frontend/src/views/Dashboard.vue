<template>
  <div>
    <n-h2>概览</n-h2>
    <n-grid :cols="4" :x-gap="16" :y-gap="16">
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
  { label: 'Token 库存', value: '-' },
  { label: '试用库存', value: '-' },
])

onMounted(async () => {
  try {
    const [stock, users, orders] = await Promise.all([
      http.get('/api/admin/tokens/stock'),
      http.get('/api/admin/users'),
      http.get('/api/admin/orders'),
    ])
    const totalStock = Object.entries(stock.data)
      .filter(([k]) => k !== '1')
      .reduce((s, [, v]) => s + v, 0)
    const today = new Date().toISOString().slice(0, 10)
    const todayOrders = orders.data.filter(o => o.created_at.startsWith(today) && o.status === 'paid').length
    stats.value = [
      { label: '用户总数', value: users.data.length },
      { label: '今日成功订单', value: todayOrders },
      { label: '付费 Token 库存', value: totalStock },
      { label: '试用 Token 库存', value: stock.data['1'] ?? 0 },
    ]
  } catch {}
})
</script>
