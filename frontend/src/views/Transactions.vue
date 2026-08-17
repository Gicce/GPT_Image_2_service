<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">账务流水</h2>
        <p class="page-header-subtitle">统一余额体系的全量计费流水：扣费 / 退款 / 充值 / 管理员调账</p>
      </div>
    </div>

    <n-card :bordered="false" class="table-card">
      <div class="filter-bar">
        <n-select
          v-model:value="filterType"
          :options="typeOptions"
          clearable
          placeholder="全部类型"
          style="width:180px"
          @update:value="() => { page = 1; load() }"
        />
        <n-select
          v-model:value="filterStatus"
          :options="statusOptions"
          clearable
          placeholder="全部状态"
          style="width:150px"
          @update:value="() => { page = 1; load() }"
        />
        <n-select
          v-model:value="filterUser"
          :options="userOptions"
          :loading="loadingUsers"
          clearable
          filterable
          placeholder="全部用户"
          style="width:220px"
          @update:value="() => { page = 1; load() }"
        />
        <n-button size="small" :loading="loading" @click="load">刷新</n-button>
      </div>

      <n-data-table
        remote
        :columns="columns"
        :data="transactions"
        :loading="loading"
        :row-key="row => row.id"
        :pagination="pagination"
        :bordered="false"
        size="small"
        @update:page="p => { page = p; load() }"
        @update:page-size="ps => { pageSize = ps; page = 1; load() }"
      />
    </n-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { NTag, NButton, useMessage, useDialog } from 'naive-ui'
import http from '../api/http'
import { formatTime } from '../utils/time'

const msg = useMessage()
const dialog = useDialog()

const transactions = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const filterType = ref(null)
const filterStatus = ref(null)
const filterUser = ref(null)
const userOptions = ref([])
const loadingUsers = ref(false)

const typeOptions = [
  { label: 'Image2 扣费', value: 'IMAGE2_CHARGE' },
  { label: 'Image2 退款', value: 'IMAGE2_REFUND' },
  { label: '充值', value: 'RECHARGE' },
  { label: '充值退款', value: 'RECHARGE_REFUND' },
  { label: '管理员调账', value: 'ADMIN_ADJUSTMENT' },
  { label: '迁移', value: 'MIGRATION' },
]

const statusOptions = [
  { label: '已预占', value: 'RESERVED' },
  { label: '成功', value: 'SUCCESS' },
  { label: '失败', value: 'FAILED' },
  { label: '已退款', value: 'REFUNDED' },
  { label: '已释放', value: 'RELEASED' },
]

const typeLabel = Object.fromEntries(typeOptions.map(o => [o.value, o.label]))
const typeTag = {
  IMAGE2_CHARGE: 'warning',
  IMAGE2_REFUND: 'success',
  RECHARGE: 'info',
  RECHARGE_REFUND: 'error',
  ADMIN_ADJUSTMENT: 'default',
  MIGRATION: 'default',
}
const statusLabel = Object.fromEntries(statusOptions.map(o => [o.value, o.label]))
const statusTag = {
  RESERVED: 'warning',
  SUCCESS: 'success',
  FAILED: 'error',
  REFUNDED: 'info',
  RELEASED: 'default',
}
const sourceLabel = { TRIAL: '试用', CASH: '现金', MIXED: '混合', NONE: '-' }

function fmt(v, digits = 4) {
  const n = Number(v)
  if (!isFinite(n)) return '0.00'
  return n.toFixed(digits)
}

const pagination = computed(() => ({
  page: page.value,
  pageSize: pageSize.value,
  itemCount: total.value,
  pageSizes: [20, 50, 100],
  showSizePicker: true,
  prefix: ({ itemCount }) => `共 ${itemCount} 条`,
}))

const columns = [
  { title: '时间', key: 'created_at', width: 150, render: row => formatTime(row.created_at) },
  { title: '用户', key: 'username', width: 110, render: row => row.username || '-' },
  {
    title: '类型', key: 'type', width: 120,
    render: row => h(NTag, { type: typeTag[row.type] || 'default', size: 'small', bordered: false },
      { default: () => typeLabel[row.type] || row.type }),
  },
  {
    title: '状态', key: 'status', width: 90,
    render: row => h(NTag, { type: statusTag[row.status] || 'default', size: 'small', bordered: false },
      { default: () => statusLabel[row.status] || row.status }),
  },
  { title: '模型', key: 'model', width: 110, render: row => row.model || '-' },
  { title: '图片数', key: 'image_count', width: 70, render: row => row.image_count ?? '-' },
  {
    title: '金额 ($)', key: 'amount_usd', width: 100,
    render: row => {
      const neg = Number(row.amount_usd) < 0
      return h('span', {
        style: `font-family:var(--cy-font-mono);${neg ? 'color:var(--cy-success)' : ''}`,
      }, fmt(row.amount_usd, 4))
    },
  },
  {
    title: '试用金额', key: 'trial_amount', width: 90,
    render: row => Number(row.trial_amount) ? `$${fmt(row.trial_amount, 4)}` : '-',
  },
  {
    title: '现金金额', key: 'balance_amount', width: 90,
    render: row => Number(row.balance_amount) ? `$${fmt(row.balance_amount, 4)}` : '-',
  },
  {
    title: '来源', key: 'billing_source', width: 70,
    render: row => sourceLabel[row.billing_source] || row.billing_source || '-',
  },
  {
    title: '失败原因', key: 'failure_reason', width: 140, ellipsis: { tooltip: true },
    render: row => row.failure_reason || '-',
  },
  {
    title: '操作', key: 'actions', width: 90,
    render: row => {
      if (row.type === 'IMAGE2_CHARGE' && row.status === 'SUCCESS') {
        return h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => refundTxn(row) },
          { default: () => '退款' })
      }
      return h('span', { style: 'color:var(--cy-text-dim)' }, '-')
    },
  },
]

async function loadUsers() {
  loadingUsers.value = true
  try {
    const { data } = await http.get('/api/admin/users')
    userOptions.value = data.map(u => ({
      label: `${u.username}${u.email ? ' (' + u.email + ')' : ''}`,
      value: u.id,
    }))
  } catch {
    userOptions.value = []
  } finally {
    loadingUsers.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (filterType.value) params.type = filterType.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterUser.value) params.user_id = filterUser.value
    const { data } = await http.get('/api/admin/billing/transactions', { params })
    transactions.value = data.transactions || []
    total.value = data.total || 0
  } catch (e) {
    msg.error(e.response?.data?.detail || '加载账务流水失败')
  } finally {
    loading.value = false
  }
}

function refundTxn(row) {
  dialog.warning({
    title: '确认退款',
    content: `对 ${row.username || '该用户'} 的 Image2 扣费流水退款 $${fmt(Math.abs(Number(row.amount_usd)), 4)}（含试用部分）？`,
    positiveText: '退款',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await http.post(`/api/admin/billing/transactions/${row.id}/refund`)
        msg.success('退款成功，金额已返还用户余额')
        await load()
      } catch (e) {
        msg.error(e.response?.data?.detail || '退款失败')
      }
    },
  })
}

onMounted(() => { load(); loadUsers() })
</script>

<style scoped>
.table-card {
  background: var(--cy-bg-elevated) !important;
  border: 1px solid var(--cy-border) !important;
  border-radius: var(--cy-radius-lg) !important;
}

.table-card :deep(.n-card__content) {
  padding: 20px !important;
}
</style>
