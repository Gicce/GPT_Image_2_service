<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">Token 库存</h2>
        <p class="page-header-subtitle">统一 Runtime Token 池，供 Image2 调度使用</p>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#00d4aa,#00d4aa00)"></div>
        <div class="stat-card-label">总 Token</div>
        <div class="stat-card-value">{{ stats.total }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#3b82f6,#3b82f600)"></div>
        <div class="stat-card-label">可用</div>
        <div class="stat-card-value">{{ stats.available }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#f59e0b,#f59e0b00)"></div>
        <div class="stat-card-label">试用可用</div>
        <div class="stat-card-value">{{ stats.trial_available }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#10b981,#10b98100)"></div>
        <div class="stat-card-label">已分配</div>
        <div class="stat-card-value">{{ stats.assigned }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#ef4444,#ef444400)"></div>
        <div class="stat-card-label">禁用</div>
        <div class="stat-card-value">{{ stats.disabled }}</div>
      </div>
    </div>

    <!-- Token 列表 -->
    <n-card :bordered="false" class="table-card">
      <div class="filter-bar">
        <n-select
          v-model:value="filterTrial"
          :options="trialOptions"
          clearable
          placeholder="全部类型"
          style="width:140px"
          @update:value="() => { page = 1; loadTokens() }"
        />
        <n-select
          v-model:value="filterAssigned"
          :options="assignedOptions"
          clearable
          placeholder="全部分配状态"
          style="width:140px"
          @update:value="() => { page = 1; loadTokens() }"
        />
        <n-input
          v-model:value="search"
          placeholder="搜索用户名 / 邮箱 / Token 片段"
          style="width:240px"
          clearable
          @keyup.enter="() => { page = 1; loadTokens() }"
          @clear="() => { page = 1; loadTokens() }"
        />
        <n-button size="small" :loading="loading" @click="refresh">刷新</n-button>
      </div>
      <n-data-table
        remote
        :columns="columns"
        :data="tokens"
        :loading="loading"
        :row-key="row => row.id"
        :pagination="pagination"
        :bordered="false"
        size="small"
        @update:page="handlePageChange"
        @update:page-size="handlePageSizeChange"
      />
    </n-card>

    <!-- 批量录入 -->
    <n-card :bordered="false" class="form-card">
      <div class="form-card-header">
        <h3 class="form-card-title">批量录入 Token</h3>
        <p class="form-card-desc">每行一条，支持 "名称 sk-xxx" 格式，自动提取 sk- 开头的 Token；重复与无效 Token 不入库，录入结果会分别提示</p>
      </div>
      <n-form-item label="Token 列表（每行一条）" label-placement="top">
        <n-input
          v-model:value="tokensRaw"
          type="textarea"
          :rows="8"
          placeholder="sk-xxxxxxxxxxxxxxxx&#10;sk-yyyyyyyyyyyyyyyy"
        />
      </n-form-item>
      <div class="form-card-footer">
        <div class="trial-switch">
          <n-switch v-model:value="batchIsTrial" />
          <span>录入为试用 Token</span>
        </div>
        <n-button type="primary" :loading="submitting" @click="submit">录入</n-button>
      </div>
    </n-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, h } from 'vue'
import { NButton, NSpace, NTag, NTooltip, useMessage, useDialog } from 'naive-ui'
import http from '../api/http'
import { formatTime } from '../utils/time'

const msg = useMessage()
const dialog = useDialog()

const stats = ref({ total: 0, available: 0, trial_available: 0, assigned: 0, disabled: 0 })
const tokens = ref([])
const loading = ref(false)
const submitting = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const filterTrial = ref(null)
const filterAssigned = ref(null)
const search = ref('')
const tokensRaw = ref('')
const batchIsTrial = ref(false)

const trialOptions = [
  { label: '试用 Token', value: true },
  { label: '正式 Token', value: false },
]
const assignedOptions = [
  { label: '已分配', value: true },
  { label: '未分配', value: false },
]

const pagination = computed(() => ({
  page: page.value,
  pageSize: pageSize.value,
  itemCount: total.value,
  pageSizes: [20, 50, 100],
  showSizePicker: true,
  prefix: ({ itemCount }) => `共 ${itemCount} 条`,
}))

function handlePageChange(p) {
  page.value = p
  loadTokens()
}

function handlePageSizeChange(ps) {
  pageSize.value = ps
  page.value = 1
  loadTokens()
}

const columns = [
  {
    title: 'Token（脱敏）', key: 'token_value', minWidth: 200,
    render: row => h('span', { style: 'font-family:var(--cy-font-mono);font-size:12px' }, row.token_value || '-'),
  },
  {
    title: '类型', key: 'is_trial', width: 80,
    render: row => h(NTag, { type: row.is_trial ? 'warning' : 'info', size: 'small', bordered: false },
      { default: () => row.is_trial ? '试用' : '正式' }),
  },
  {
    title: '分配用户', key: 'is_assigned', minWidth: 220,
    render: row => {
      if (!row.is_assigned) {
        return h(NTag, { size: 'small', bordered: false }, { default: () => '未分配' })
      }
      const name = row.assigned_username || ''
      const email = row.assigned_email || ''
      const who = row.assigned_to || ''
      const children = [
        h(NTag, { type: 'success', size: 'small', bordered: false }, { default: () => '已分配' }),
      ]
      if (name || email) {
        children.push(h(NTooltip, { trigger: 'hover' }, {
          trigger: () => h(
            'span',
            { style: 'display:inline-flex;flex-direction:column;line-height:1.3;cursor:default' },
            [
              h('span', { style: 'font-size:12px;color:var(--cy-text)' }, name || '（未知用户）'),
              h('span', { style: 'font-size:11px;color:var(--cy-text-muted)' }, email),
            ]
          ),
          default: () => `用户 ID：${who}${row.assigned_at ? ' · 分配于 ' + formatTime(row.assigned_at) : ''}`,
        }))
      } else if (who) {
        // 用户已被删除等场景：回落显示缩略 ID
        children.push(h(NTooltip, { trigger: 'hover' }, {
          trigger: () => h('span', { style: 'font-family:var(--cy-font-mono);font-size:11px;color:var(--cy-text-muted);cursor:pointer' }, who.slice(0, 8) + '…'),
          default: () => `用户 ID：${who}（用户不存在）`,
        }))
      }
      return h(NSpace, { size: 8, align: 'center', wrapItem: false }, { default: () => children })
    },
  },
  {
    title: '状态', key: 'is_disabled', width: 80,
    render: row => h(NTag, { type: row.is_disabled ? 'error' : 'success', size: 'small', bordered: false },
      { default: () => row.is_disabled ? '已禁用' : '正常' }),
  },
  {
    title: '录入时间', key: 'created_at', width: 160,
    render: row => formatTime(row.created_at),
  },
  {
    title: '操作', key: 'actions', width: 140,
    render: row => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, {
          size: 'small', quaternary: true,
          type: row.is_disabled ? 'success' : 'warning',
          onClick: () => toggleDisabled(row),
        }, { default: () => row.is_disabled ? '启用' : '禁用' }),
        h(NButton, {
          size: 'small', quaternary: true, type: 'error',
          disabled: row.is_assigned,
          onClick: () => removeToken(row),
        }, { default: () => '删除' }),
      ]
    }),
  },
]

async function loadStats() {
  try {
    const { data } = await http.get('/api/admin/tokens/stats')
    stats.value = data
  } catch {}
}

async function loadTokens() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (filterTrial.value !== null && filterTrial.value !== undefined) params.is_trial = filterTrial.value
    if (filterAssigned.value !== null && filterAssigned.value !== undefined) params.is_assigned = filterAssigned.value
    if (search.value && search.value.trim()) params.search = search.value.trim()
    const { data } = await http.get('/api/admin/tokens', { params })
    tokens.value = data.tokens || []
    total.value = data.total || 0
  } catch (e) {
    msg.error(e.response?.data?.detail || '加载 Token 列表失败')
  } finally {
    loading.value = false
  }
}

function refresh() {
  loadStats()
  loadTokens()
}

async function toggleDisabled(row) {
  try {
    await http.put(`/api/admin/tokens/${row.id}`, { is_disabled: !row.is_disabled })
    msg.success(row.is_disabled ? '已启用' : '已禁用')
    refresh()
  } catch (e) {
    msg.error(e.response?.data?.detail || '操作失败')
  }
}

function removeToken(row) {
  dialog.warning({
    title: '确认删除',
    content: `确定删除 Token ${row.token_value} 吗？已分配的 Token 无法删除。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await http.delete(`/api/admin/tokens/${row.id}`)
        msg.success('已删除')
        refresh()
      } catch (e) {
        msg.error(e.response?.data?.detail || '删除失败')
      }
    },
  })
}

async function submit() {
  const lines = tokensRaw.value.split(/\r?\n/).map(t => t.trim()).filter(Boolean)
  if (!lines.length) return msg.warning('请输入至少一个 Token')
  submitting.value = true
  try {
    const { data } = await http.post('/api/admin/tokens/batch', {
      tokens: lines,
      is_trial: batchIsTrial.value,
    })
    const added = data.added ?? 0
    const duplicate = data.duplicate ?? 0
    const invalid = data.invalid ?? 0
    const message = buildImportMessage(added, duplicate, invalid)
    if (added > 0) {
      msg.success(message)
      tokensRaw.value = ''
    } else {
      // 没有任何新增：保留输入内容，方便管理员核对重复/无效原因
      msg.warning(message)
    }
    refresh()
  } catch (e) {
    msg.error(e.response?.data?.detail || '录入失败')
  } finally {
    submitting.value = false
  }
}

function buildImportMessage(added, duplicate, invalid) {
  if (duplicate === 0 && invalid === 0) return `成功录入 ${added} 个 Token`
  if (added === 0 && duplicate > 0 && invalid === 0) return `没有新增 Token：${duplicate} 个 Token 已存在`
  const parts = [`成功 ${added} 个`]
  if (duplicate > 0) parts.push(`重复 ${duplicate} 个`)
  if (invalid > 0) parts.push(`无效 ${invalid} 个`)
  return `录入完成：${parts.join('，')}`
}

onMounted(refresh)
</script>

<style scoped>
.stats-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

@media (max-width: 1200px) {
  .stats-row {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
}

.stat-card {
  position: relative;
  background: var(--cy-bg-elevated);
  border: 1px solid var(--cy-border);
  border-radius: var(--cy-radius-lg);
  padding: 20px 24px;
  overflow: hidden;
}

.stat-card-accent {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
}

.stat-card-label {
  font-size: 13px;
  color: var(--cy-text-muted);
  margin-bottom: 4px;
}

.stat-card-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--cy-text);
  font-family: var(--cy-font-mono);
}

.table-card {
  background: var(--cy-bg-elevated) !important;
  border: 1px solid var(--cy-border) !important;
  border-radius: var(--cy-radius-lg) !important;
  margin-bottom: 20px;
}

.table-card :deep(.n-card__content) {
  padding: 20px !important;
}

.form-card {
  background: var(--cy-bg-elevated) !important;
  border: 1px solid var(--cy-border) !important;
  border-radius: var(--cy-radius-lg) !important;
}

.form-card :deep(.n-card__content) {
  padding: 24px !important;
}

.form-card-header {
  margin-bottom: 20px;
}

.form-card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--cy-text);
}

.form-card-desc {
  font-size: 12px;
  color: var(--cy-text-muted);
  margin-top: 4px;
}

.form-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
}

.trial-switch {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--cy-text-secondary);
}
</style>
