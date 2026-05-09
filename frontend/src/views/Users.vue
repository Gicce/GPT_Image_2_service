<template>
  <div>
    <n-h2>用户列表</n-h2>
    <div style="display:flex;gap:12px;margin-bottom:16px">
      <n-select v-model:value="filterType" :options="typeOptions" clearable placeholder="筛选类型" style="width:160px" />
      <n-input v-model:value="search" placeholder="搜索用户名 / 邮箱" style="width:260px" clearable />
    </div>
    <n-data-table :columns="columns" :data="filtered" :pagination="{ pageSize: 20 }" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { NTag } from 'naive-ui'
import http from '../api/http'

const users = ref([])
const filterType = ref(null)
const search = ref('')

const typeOptions = [
  { label: '试用', value: 'trial' },
  { label: '付费', value: 'paid' },
]

const typeTag = { trial: 'warning', paid: 'success' }
const typeLabel = { trial: '试用', paid: '付费' }

const filtered = computed(() => {
  let list = users.value
  if (filterType.value) list = list.filter(u => u.account_type === filterType.value)
  if (search.value) {
    const q = search.value.toLowerCase()
    list = list.filter(u =>
      (u.username || '').toLowerCase().includes(q) ||
      (u.email || '').toLowerCase().includes(q)
    )
  }
  return list
})

const columns = [
  { title: 'ID', key: 'id', width: 60 },
  { title: '用户名', key: 'username', width: 140 },
  { title: '邮箱', key: 'email', width: 200 },
  { title: '类型', key: 'account_type', width: 80,
    render: row => h(NTag, { type: typeTag[row.account_type] || 'default', size: 'small' },
      { default: () => typeLabel[row.account_type] || row.account_type }) },
  { title: '余额($)', key: 'balance_usd', width: 90,
    render: row => `$${Number(row.balance_usd || 0).toFixed(4)}` },
  { title: '状态', key: 'is_active', width: 80,
    render: row => h(NTag, { type: row.is_active ? 'success' : 'error', size: 'small' },
      { default: () => row.is_active ? '正常' : '禁用' }) },
  { title: '试用到期', key: 'trial_expires_at', width: 160,
    render: row => row.trial_expires_at ? row.trial_expires_at.replace('T', ' ').slice(0, 19) : '-' },
  { title: '注册时间', key: 'created_at', width: 160,
    render: row => row.created_at?.replace('T', ' ').slice(0, 19) },
]

onMounted(async () => {
  const { data } = await http.get('/api/admin/users')
  users.value = data
})
</script>
