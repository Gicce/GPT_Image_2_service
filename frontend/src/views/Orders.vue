<template>
  <div>
    <n-h2>订单列表</n-h2>
    <div style="display:flex;gap:12px;margin-bottom:16px">
      <n-select v-model:value="filterStatus" :options="statusOptions" clearable placeholder="筛选状态" style="width:160px" />
      <n-input v-model:value="search" placeholder="搜索用户名 / 订单号" style="width:260px" clearable />
    </div>
    <n-data-table :columns="columns" :data="filtered" :pagination="{ pageSize: 20 }" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { NTag } from 'naive-ui'
import http from '../api/http'

const orders = ref([])
const filterStatus = ref(null)
const search = ref('')

const statusOptions = [
  { label: '待支付', value: 'pending' },
  { label: '已支付', value: 'paid' },
  { label: '已关闭', value: 'closed' },
]

const statusTag = { pending: 'warning', paid: 'success', closed: 'default' }
const statusLabel = { pending: '待支付', paid: '已支付', closed: '已关闭' }

const filtered = computed(() => {
  let list = orders.value
  if (filterStatus.value) list = list.filter(o => o.status === filterStatus.value)
  if (search.value) {
    const q = search.value.toLowerCase()
    list = list.filter(o =>
      (o.username || '').toLowerCase().includes(q) ||
      (o.out_trade_no || '').toLowerCase().includes(q)
    )
  }
  return list
})

const columns = [
  { title: '订单号', key: 'out_trade_no', width: 200, ellipsis: true },
  { title: '用户', key: 'username', width: 120 },
  { title: '套餐', key: 'package_usd', width: 80,
    render: row => `$${row.package_usd}` },
  { title: '金额(CNY)', key: 'amount_cny', width: 100,
    render: row => `¥${Number(row.amount_cny).toFixed(2)}` },
  { title: '汇率', key: 'exchange_rate', width: 80,
    render: row => Number(row.exchange_rate).toFixed(4) },
  { title: '支付方式', key: 'pay_type', width: 90 },
  { title: '状态', key: 'status', width: 90,
    render: row => h(NTag, { type: statusTag[row.status] || 'default', size: 'small' },
      { default: () => statusLabel[row.status] || row.status }) },
  { title: '创建时间', key: 'created_at', width: 160,
    render: row => row.created_at?.replace('T', ' ').slice(0, 19) },
  { title: '支付时间', key: 'paid_at', width: 160,
    render: row => row.paid_at ? row.paid_at.replace('T', ' ').slice(0, 19) : '-' },
]

onMounted(async () => {
  const { data } = await http.get('/api/admin/orders')
  orders.value = data
})
</script>
