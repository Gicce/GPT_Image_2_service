<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">Runtime Token</h2>
        <p class="page-header-subtitle">共享 Token 池：一枚 Token 可服务多个用户；新用户自动绑定对应类型的默认 Token</p>
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
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#10b981,#10b98100)"></div>
        <div class="stat-card-label">正常</div>
        <div class="stat-card-value">{{ stats.available }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#3b82f6,#3b82f600)"></div>
        <div class="stat-card-label">正式</div>
        <div class="stat-card-value">{{ stats.paid }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#f59e0b,#f59e0b00)"></div>
        <div class="stat-card-label">试用</div>
        <div class="stat-card-value">{{ stats.trial }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#8b5cf6,#8b5cf600)"></div>
        <div class="stat-card-label">默认</div>
        <div class="stat-card-value">{{ stats.defaults }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#ef4444,#ef444400)"></div>
        <div class="stat-card-label">不可用</div>
        <div class="stat-card-value">{{ (stats.disabled || 0) + (stats.expired || 0) }}</div>
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
          style="width:120px"
          @update:value="() => { page = 1; loadTokens() }"
        />
        <n-select
          v-model:value="filterStatus"
          :options="statusOptions"
          clearable
          placeholder="全部状态"
          style="width:120px"
          @update:value="() => { page = 1; loadTokens() }"
        />
        <n-input
          v-model:value="search"
          placeholder="搜索名称 / Token 片段 / 用户"
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
      <n-form-item label="Token 名称（可选）" label-placement="top">
        <n-input v-model:value="batchName" placeholder="如：主正式 Token / 试用线路 01" />
      </n-form-item>
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

    <!-- Token 详情（关联用户） -->
    <n-modal v-model:show="showDetail" preset="card" :title="`Token 详情${detail?.name ? ' · ' + detail.name : ''}`" style="width:720px">
      <n-descriptions v-if="detail" :column="3" bordered label-placement="left" size="small">
        <n-descriptions-item label="Token（脱敏）" :span="2">
          <span style="font-family:var(--cy-font-mono);font-size:12px">{{ detail.token_value }}</span>
        </n-descriptions-item>
        <n-descriptions-item label="状态">
          <n-tag :type="tokenStatusTag[detail.status] || 'default'" size="small" :bordered="false">
            {{ tokenStatusLabel[detail.status] || detail.status }}
          </n-tag>
        </n-descriptions-item>
        <n-descriptions-item label="类型">{{ detail.is_trial ? '试用' : '正式' }}</n-descriptions-item>
        <n-descriptions-item label="默认">
          <n-tag v-if="detail.is_default" type="success" size="small" :bordered="false">默认</n-tag>
          <span v-else>-</span>
        </n-descriptions-item>
        <n-descriptions-item label="关联用户">{{ detail.user_count }} 人</n-descriptions-item>
        <n-descriptions-item label="额度">
          {{ detail.quota_usd === null || detail.quota_usd === undefined ? '无限' : `$${Number(detail.quota_usd).toFixed(2)}（已用 $${Number(detail.used_usd || 0).toFixed(2)}）` }}
        </n-descriptions-item>
        <n-descriptions-item label="过期时间">{{ detail.expires_at ? formatTime(detail.expires_at) : '永久有效' }}</n-descriptions-item>
        <n-descriptions-item label="创建时间">{{ formatTime(detail.created_at) }}</n-descriptions-item>
      </n-descriptions>
      <div class="filter-bar" style="margin-top:16px">
        <n-input
          v-model:value="detailSearch"
          placeholder="搜索用户名 / 邮箱"
          style="width:240px"
          clearable
          @keyup.enter="loadDetail"
          @clear="loadDetail"
        />
        <n-button size="small" @click="loadDetail">搜索</n-button>
      </div>
      <n-data-table
        :columns="userColumns"
        :data="detail?.users || []"
        :row-key="row => row.user_id"
        :bordered="false"
        size="small"
        :pagination="{ pageSize: 10 }"
      />
    </n-modal>

    <!-- 编辑 Token -->
    <n-modal v-model:show="showEdit" preset="card" title="编辑 Token" style="width:480px">
      <n-form v-if="editForm" label-placement="left" label-width="90">
        <n-form-item label="名称">
          <n-input v-model:value="editForm.name" placeholder="如：主正式 Token" />
        </n-form-item>
        <n-form-item label="额度">
          <n-radio-group v-model:value="editForm.quotaMode">
            <n-radio value="unlimited">无限</n-radio>
            <n-radio value="custom">自定义（USD）</n-radio>
          </n-radio-group>
        </n-form-item>
        <n-form-item v-if="editForm.quotaMode === 'custom'" label="额度($)">
          <n-input-number v-model:value="editForm.quota_usd" :precision="2" :min="0" style="width:100%" />
        </n-form-item>
        <n-form-item label="过期时间">
          <n-radio-group v-model:value="editForm.expireMode">
            <n-radio value="never">永久有效</n-radio>
            <n-radio value="date">指定时间</n-radio>
          </n-radio-group>
        </n-form-item>
        <n-form-item v-if="editForm.expireMode === 'date'" label="过期至">
          <n-date-picker v-model:value="editForm.expires_ts" type="datetime" clearable style="width:100%" />
        </n-form-item>
        <n-form-item label="启用">
          <n-switch :value="!editForm.is_disabled" @update:value="v => editForm.is_disabled = !v" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showEdit = false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="saveEdit">保存</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { NButton, NSpace, NTag, useMessage, useDialog } from 'naive-ui'
import http from '../api/http'
import { formatTime } from '../utils/time'

const msg = useMessage()
const dialog = useDialog()

const stats = ref({ total: 0, available: 0, paid: 0, trial: 0, defaults: 0, disabled: 0, expired: 0, active_bindings: 0 })
const tokens = ref([])
const loading = ref(false)
const submitting = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const filterTrial = ref(null)
const filterStatus = ref(null)
const search = ref('')
const tokensRaw = ref('')
const batchName = ref('')
const batchIsTrial = ref(false)

// 详情 / 编辑
const showDetail = ref(false)
const detail = ref(null)
const detailSearch = ref('')
const showEdit = ref(false)
const editForm = ref(null)
const editTokenId = ref(null)
const saving = ref(false)

const trialOptions = [
  { label: '试用 Token', value: true },
  { label: '正式 Token', value: false },
]
const statusOptions = [
  { label: '正常', value: 'active' },
  { label: '禁用', value: 'disabled' },
  { label: '过期', value: 'expired' },
  { label: '额度耗尽', value: 'exhausted' },
]

const tokenStatusTag = { active: 'success', disabled: 'error', expired: 'warning', exhausted: 'warning' }
const tokenStatusLabel = { active: '正常', disabled: '禁用', expired: '过期', exhausted: '额度耗尽' }

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
    title: '名称', key: 'name', width: 130, ellipsis: true,
    render: row => row.name || h('span', { style: 'color:var(--cy-text-dim)' }, '（未命名）'),
  },
  {
    title: 'Token（脱敏）', key: 'token_value', minWidth: 170,
    render: row => h('span', { style: 'font-family:var(--cy-font-mono);font-size:12px' }, row.token_value || '-'),
  },
  {
    title: '类型', key: 'is_trial', width: 70,
    render: row => h(NTag, { type: row.is_trial ? 'warning' : 'info', size: 'small', bordered: false },
      { default: () => row.is_trial ? '试用' : '正式' }),
  },
  {
    title: '额度', key: 'quota', width: 130,
    render: row => row.quota_usd === null || row.quota_usd === undefined
      ? h('span', { style: 'color:var(--cy-text-muted)' }, '无限')
      : `$${Number(row.quota_usd).toFixed(2)} / 用 $${Number(row.used_usd || 0).toFixed(2)}`,
  },
  {
    title: '默认路由', key: 'is_default', width: 100,
    render: row => row.is_default
      ? h(NTag, { type: 'success', size: 'small', bordered: false },
          { default: () => row.is_trial ? '试用默认' : '正式默认' })
      : '-',
  },
  {
    title: '状态', key: 'status', width: 90,
    render: row => h(NTag, { type: tokenStatusTag[row.status] || 'default', size: 'small', bordered: false },
      { default: () => tokenStatusLabel[row.status] || row.status }),
  },
  {
    title: '过期时间', key: 'expires_at', width: 130,
    render: row => row.expires_at ? formatTime(row.expires_at) : '永久',
  },
  {
    title: '关联用户', key: 'user_count', width: 80,
    render: row => h('span', { style: 'font-weight:600' }, String(row.user_count ?? 0)),
  },
  {
    title: '创建时间', key: 'created_at', width: 130,
    render: row => formatTime(row.created_at),
  },
  {
    title: '操作', key: 'actions', width: 300,
    render: row => h(NSpace, { size: 'small' }, {
      default: () => {
        const btns = [
          h(NButton, { size: 'small', quaternary: true, type: 'info', onClick: () => openDetail(row) }, { default: () => '查看' }),
          h(NButton, { size: 'small', quaternary: true, type: 'warning', onClick: () => openEdit(row) }, { default: () => '编辑' }),
        ]
        if (!row.is_default) {
          btns.push(h(NButton, { size: 'small', quaternary: true, type: 'success', onClick: () => setDefault(row) }, { default: () => '设为默认' }))
        }
        btns.push(h(NButton, {
          size: 'small', quaternary: true,
          type: row.status === 'disabled' ? 'success' : 'warning',
          onClick: () => toggleDisabled(row),
        }, { default: () => row.status === 'disabled' ? '启用' : '禁用' }))
        btns.push(h(NButton, {
          size: 'small', quaternary: true, type: 'error',
          onClick: () => removeToken(row),
        }, { default: () => '删除' }))
        return btns
      }
    }),
  },
]

const userColumns = [
  { title: '用户名', key: 'username', render: row => row.username || '-' },
  { title: '邮箱', key: 'email', ellipsis: true, render: row => row.email || '-' },
  { title: '账户类型', key: 'account_type', width: 90,
    render: row => h(NTag, { size: 'small', bordered: false,
      type: row.account_type === 'paid' ? 'success' : row.account_type === 'trial' ? 'warning' : 'default' },
      { default: () => row.account_type || '-' }) },
  { title: '绑定时间', key: 'assigned_at', width: 150, render: row => formatTime(row.assigned_at) },
  { title: '绑定状态', key: 'assignment_status', width: 90,
    render: row => h(NTag, { size: 'small', bordered: false, type: 'success' }, { default: () => '生效中' }) },
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
    if (filterStatus.value) params.status = filterStatus.value
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

async function openDetail(row) {
  detailSearch.value = ''
  await loadDetail(row.id)
  showDetail.value = true
}

async function loadDetail() {
  if (!detail.value) return
  try {
    const params = {}
    if (detailSearch.value && detailSearch.value.trim()) params.search = detailSearch.value.trim()
    const { data } = await http.get(`/api/admin/tokens/${detail.value.id}`, { params })
    detail.value = data
  } catch (e) {
    msg.error(e.response?.data?.detail || '加载详情失败')
  }
}

function openEdit(row) {
  editTokenId.value = row.id
  editForm.value = {
    name: row.name || '',
    is_disabled: row.status === 'disabled',
    quotaMode: (row.quota_usd === null || row.quota_usd === undefined) ? 'unlimited' : 'custom',
    quota_usd: row.quota_usd !== null && row.quota_usd !== undefined ? Number(row.quota_usd) : null,
    expireMode: row.expires_at ? 'date' : 'never',
    expires_ts: row.expires_at ? new Date(row.expires_at).getTime() : null,
  }
  showEdit.value = true
}

async function saveEdit() {
  const f = editForm.value
  saving.value = true
  try {
    const body = { name: f.name || null, is_disabled: f.is_disabled, keep_expires: false }
    if (f.quotaMode === 'unlimited') {
      body.quota_unlimited = true
    } else if (f.quota_usd !== null && f.quota_usd !== undefined) {
      body.quota_usd = f.quota_usd
    }
    if (f.expireMode === 'date' && f.expires_ts) {
      body.expires_at = new Date(f.expires_ts).toISOString()
    } else {
      body.expires_at = ''
    }
    await http.put(`/api/admin/tokens/${editTokenId.value}`, body)
    msg.success('已保存')
    showEdit.value = false
    refresh()
  } catch (e) {
    msg.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

function setDefault(row) {
  dialog.warning({
    title: '设为默认',
    content: `确定把「${row.name || row.token_value}」设为${row.is_trial ? '试用' : '正式'}类型默认 Token 吗？同类型原默认将被取消。已绑定用户不受影响，仅新注册试用 / 新充值用户自动绑定新默认。`,
    positiveText: '设为默认',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await http.post(`/api/admin/tokens/${row.id}/set-default`)
        msg.success('已设为默认')
        refresh()
      } catch (e) {
        msg.error(e.response?.data?.detail || '操作失败')
      }
    },
  })
}

async function toggleDisabled(row) {
  try {
    await http.put(`/api/admin/tokens/${row.id}`, { is_disabled: row.status !== 'disabled', keep_expires: true })
    msg.success(row.status === 'disabled' ? '已启用' : '已禁用')
    refresh()
  } catch (e) {
    msg.error(e.response?.data?.detail || '操作失败')
  }
}

function removeToken(row) {
  const users = row.user_count ?? 0
  dialog.warning({
    title: '确认删除',
    content: users > 0
      ? `该 Token 当前关联 ${users} 个用户，禁止直接删除。请先在用户详情中解绑，或改用「禁用」。`
      : `确定删除 Token ${row.token_value} 吗？此操作不可恢复。`,
    positiveText: users > 0 ? '知道了' : '删除',
    negativeText: users > 0 ? undefined : '取消',
    showIcon: users > 0,
    onPositiveClick: async () => {
      if (users > 0) return
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
    const body = { tokens: lines, is_trial: batchIsTrial.value }
    if (batchName.value.trim()) body.name = batchName.value.trim()
    const { data } = await http.post('/api/admin/tokens/batch', body)
    const added = data.added ?? 0
    const duplicate = data.duplicate ?? 0
    const invalid = data.invalid ?? 0
    const message = buildImportMessage(added, duplicate, invalid)
    if (added > 0) {
      msg.success(message)
      tokensRaw.value = ''
    } else {
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
  grid-template-columns: repeat(6, 1fr);
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
