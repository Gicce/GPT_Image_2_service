<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">成本与毛利</h2>
        <p class="page-header-subtitle">经营账：任务收入 / 采购成本 / 毛利润（试用与赠送消耗单列为获客成本）</p>
      </div>
      <n-button size="small" type="primary" @click="load" :loading="loading">刷新</n-button>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#00d4aa,#00d4aa00)"></div>
        <div class="stat-card-label">付费收入（¥）</div>
        <div class="stat-card-value">{{ money(summary.revenue_rmb) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#f59e0b,#f59e0b00)"></div>
        <div class="stat-card-label">采购成本（¥）</div>
        <div class="stat-card-value">{{ money(summary.actual_cost_rmb) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#6366f1,#6366f100)"></div>
        <div class="stat-card-label">毛利润（¥）</div>
        <div class="stat-card-value">{{ money(summary.gross_profit_rmb) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#0f766e,#0f766e00)"></div>
        <div class="stat-card-label">综合毛利率</div>
        <div class="stat-card-value">{{ summary.gross_margin ? pct(summary.gross_margin) : '-' }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#ec4899,#ec489900)"></div>
        <div class="stat-card-label">获客价值（试用/赠送点）</div>
        <div class="stat-card-value">{{ money(summary.promotional_value_rmb) }}</div>
      </div>
    </div>

    <div class="filter-bar">
      <n-date-picker v-model:value="dateRange" type="daterange" clearable size="small" style="width:260px" />
      <n-select v-model:value="filters.category" :options="categoryOptions" size="small" style="width:140px"
        placeholder="收入分类" clearable @update:value="load" />
      <n-input v-model:value="filters.request_id" size="small" style="width:220px" placeholder="Task / Request ID"
        clearable @keyup.enter="load" />
      <n-button size="small" @click="load">查询</n-button>
    </div>

    <div class="table-card">
      <n-data-table :columns="columns" :data="records" :loading="loading" :bordered="false"
        :pagination="{ pageSize: 20 }" :row-key="row => row.id" remote :page="page" :item-count="total"
        @update:page="p => { page = p; load() }" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, h } from 'vue'
import { NTag } from 'naive-ui'
import http from '../api/http'

const loading = ref(false)
const records = ref([])
const summary = ref({})
const total = ref(0)
const page = ref(1)
const dateRange = ref(null)
const filters = ref({ category: null, request_id: '' })

const categoryOptions = [
  { label: '付费', value: 'paid' },
  { label: '试用（获客）', value: 'trial' },
  { label: '赠送（营销）', value: 'gift' },
  { label: '混合', value: 'mixed' },
]

const columns = [
  { title: '结算时间', key: 'settled_at', width: 160,
    render: r => r.settled_at ? new Date(r.settled_at).toLocaleString('zh-CN', { hour12: false }) : '-' },
  { title: '用户', key: 'username', width: 110, render: r => r.username || r.user_id?.slice(0, 8) || '-' },
  { title: '分类', key: 'category', width: 90,
    render: r => h(NTag, {
      type: r.category === 'paid' ? 'success' : r.category === 'trial' ? 'warning' : 'info',
      size: 'small', bordered: false,
    }, { default: () => ({ paid: '付费', trial: '试用', gift: '赠送', mixed: '混合', none: '-' })[r.category] || r.category }) },
  { title: '预占/结算/释放', key: 'credits', width: 140,
    render: r => `${r.reserved_credits} / ${r.charged_credits} / ${r.released_credits}` },
  { title: '收入（¥）', key: 'revenue_rmb', width: 100, render: r => money(r.revenue_rmb) },
  { title: '获客价值（¥）', key: 'promotional_value_rmb', width: 110, render: r => money(r.promotional_value_rmb) },
  { title: '成本（¥）', key: 'actual_cost_rmb', width: 100, render: r => money(r.actual_cost_rmb) },
  { title: '毛利（¥）', key: 'gross_profit_rmb', width: 100, render: r => money(r.gross_profit_rmb) },
  { title: '毛利率', key: 'gross_margin', width: 90, render: r => pct(r.gross_margin) },
  { title: '成功/失败', key: 'units', width: 90, render: r => `${r.successful_units} / ${r.failed_units}` },
  { title: '路由', key: 'provider_route', width: 110 },
  { title: '规则版本', key: 'pricing_rule_version', width: 90,
    render: r => r.pricing_rule_version ? `v${r.pricing_rule_version}` : '-' },
  { title: 'Request ID', key: 'request_id', width: 140,
    render: r => r.request_id ? r.request_id.slice(0, 16) + (r.request_id.length > 16 ? '…' : '') : '-' },
]

function money(v) { return v == null ? '-' : '¥' + parseFloat(v).toFixed(4) }
function pct(v) { return v == null ? '-' : (parseFloat(v) * 100).toFixed(1) + '%' }

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: 20 }
    if (filters.value.category) params.category = filters.value.category
    if (filters.value.request_id?.trim()) params.request_id = filters.value.request_id.trim()
    if (dateRange.value && dateRange.value[0]) {
      params.start_date = new Date(dateRange.value[0]).toISOString().slice(0, 10)
      params.end_date = new Date(dateRange.value[1]).toISOString().slice(0, 10)
    }
    const { data } = await http.get('/api/admin/margin/ledger', { params })
    records.value = data.records || []
    summary.value = data.summary || {}
    total.value = data.total || 0
  } catch (e) {
    console.error('margin ledger load failed', e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.stats-row { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
.stat-card { position: relative; background: #fff; border-radius: var(--cy-radius); border: 1px solid var(--cy-border); padding: 20px 24px; min-width: 170px; overflow: hidden; }
.stat-card-accent { position: absolute; top: 0; left: 0; right: 0; height: 3px; }
.stat-card-label { font-size: 13px; color: var(--cy-text-muted); margin-bottom: 4px; }
.stat-card-value { font-size: 24px; font-weight: 700; color: var(--cy-text); font-family: var(--cy-font-mono); }
.filter-bar { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.table-card { background: #fff; border: 1px solid var(--cy-border); border-radius: var(--cy-radius); padding: 16px 20px; }
</style>
