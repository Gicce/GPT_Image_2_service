<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">客户账户</h2>
        <p class="page-header-subtitle">CY 点数统一账户：正式、试用与赠送点数</p>
      </div>
    </div>

    <div class="filter-bar">
      <n-select v-model:value="filterType" :options="typeOptions" clearable placeholder="筛选类型" style="width:160px" />
      <n-select v-model:value="filterStatus" :options="statusOptions" clearable placeholder="筛选状态" style="width:160px" />
      <n-input v-model:value="search" placeholder="搜索用户名 / 邮箱" style="width:260px" clearable />
    </div>

    <n-data-table
      :columns="columns"
      :data="filtered"
      :pagination="{ pageSize: 20 }"
      :row-key="row => row.id"
      :bordered="false"
      :scroll-x="tableScrollX"
    />

    <!-- 查看用户详情 -->
    <n-modal v-model:show="showDetail" preset="card" title="用户详情"
      style="width:min(920px,calc(100vw - 48px));max-height:calc(100vh - 48px)" content-style="overflow:auto">
      <template v-if="detailUser">
        <n-descriptions :column="viewportWidth < 1200 ? 1 : 2" bordered label-placement="left" size="small">
          <n-descriptions-item label="用户名">{{ detailUser.username }}</n-descriptions-item>
          <n-descriptions-item label="邮箱">{{ detailUser.email }}</n-descriptions-item>
          <n-descriptions-item label="类型">
            <n-tag :type="typeTag[detailUser.account_type] || 'default'" size="small" :bordered="false">
              {{ typeLabel[detailUser.account_type] || detailUser.account_type }}
            </n-tag>
          </n-descriptions-item>
          <n-descriptions-item label="状态">
            <n-tag :type="detailUser.archived_at ? 'default' : (detailUser.is_active ? 'success' : 'error')" size="small" :bordered="false">
              {{ detailUser.archived_at ? '已归档' : (detailUser.is_active ? '正常' : '禁用') }}
            </n-tag>
          </n-descriptions-item>
          <n-descriptions-item label="注册时间">{{ formatTime(detailUser.created_at) }}</n-descriptions-item>
          <n-descriptions-item label="试用到期">
            {{ detailUser.trial_expires_at ? formatTime(detailUser.trial_expires_at) : '-' }}
          </n-descriptions-item>
        </n-descriptions>

        <n-divider style="margin:16px 0 12px">Image2 Runtime</n-divider>
        <div class="runtime-token-box">
          <template v-if="detailUser.runtime_token">
            <div class="runtime-token-row">
              <span class="runtime-token-label">Runtime Token</span>
              <span class="runtime-token-value">{{ detailUser.runtime_token.masked_token }}</span>
              <n-tag :type="detailUser.runtime_token.is_trial ? 'warning' : 'info'" size="small" :bordered="false">
                {{ detailUser.runtime_token.is_trial ? '试用' : '正式' }}
              </n-tag>
              <n-tag :type="detailUser.runtime_token.is_disabled ? 'error' : 'success'" size="small" :bordered="false">
                {{ detailUser.runtime_token.is_disabled ? '已禁用' : '正常' }}
              </n-tag>
            </div>
            <div class="runtime-token-row sub">
              <span class="runtime-token-label">分配时间</span>
              <span class="runtime-token-value">{{ detailUser.runtime_token.assigned_at ? formatTime(detailUser.runtime_token.assigned_at) : '-' }}</span>
            </div>
          </template>
          <p v-else class="runtime-token-empty">尚未分配 Image2 Runtime Token（生成时回落使用服务端 Master Token）</p>
          <n-space v-if="!detailUser.archived_at" size="small">
            <n-button size="small" type="primary" secondary :loading="assignSubmitting" @click="openAssignToken">
              {{ detailUser.runtime_token ? '更换 Token' : '分配 Token' }}
            </n-button>
            <n-button v-if="detailUser.runtime_token" size="small" type="warning" secondary :loading="releaseLoading" @click="releaseToken">
              解除绑定
            </n-button>
          </n-space>
        </div>

        <n-divider style="margin:16px 0 12px">余额与消费</n-divider>
        <div class="detail-stats">
          <div class="stat-card">
            <div class="stat-card-accent" style="background:linear-gradient(90deg,#00d4aa,#00d4aa00)"></div>
            <div class="stat-card-label">正式点数</div>
            <div class="stat-card-value">{{ detailUser.paid_credits ?? 0 }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-card-accent" style="background:linear-gradient(90deg,#f59e0b,#f59e0b00)"></div>
            <div class="stat-card-label">试用点数</div>
            <div class="stat-card-value">{{ detailUser.trial_credits ?? 0 }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-card-accent" style="background:linear-gradient(90deg,#6366f1,#6366f100)"></div>
            <div class="stat-card-label">赠送点数</div>
            <div class="stat-card-value">{{ detailUser.gift_credits ?? 0 }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-card-accent" style="background:linear-gradient(90deg,#3b82f6,#3b82f600)"></div>
            <div class="stat-card-label">累计充值（点）</div>
            <div class="stat-card-value">{{ detailUser.total_recharged_credits ?? 0 }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-card-accent" style="background:linear-gradient(90deg,#ec4899,#ec489900)"></div>
            <div class="stat-card-label">累计消费（点）</div>
            <div class="stat-card-value">{{ detailUser.total_spent_credits ?? 0 }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-card-accent" style="background:linear-gradient(90deg,#10b981,#10b98100)"></div>
            <div class="stat-card-label">Image2 调用次数</div>
            <div class="stat-card-value">{{ detailUser.image2_call_count ?? 0 }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-card-accent" style="background:linear-gradient(90deg,#64748b,#64748b00)"></div>
            <div class="stat-card-label">累计出图</div>
            <div class="stat-card-value">{{ detailUser.image2_image_count ?? 0 }}</div>
          </div>
        </div>

        <n-divider style="margin:16px 0 12px">最近用量</n-divider>
        <n-data-table
          v-if="detailUser.usage_logs && detailUser.usage_logs.length"
          :columns="usageColumns"
          :data="detailUser.usage_logs"
          :pagination="{ pageSize: 10 }"
          size="small"
          :max-height="240"
          :bordered="false"
        />
        <n-empty v-else description="暂无用量记录" size="small" />
      </template>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showDetail = false">关闭</n-button>
          <n-button type="primary" @click="openBalance(detailUser)">调整余额</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 编辑用户 -->
    <n-modal v-model:show="showEdit" preset="card" title="编辑用户"
      style="width:min(560px,calc(100vw - 48px));max-height:calc(100vh - 48px)" content-style="overflow:auto">
      <n-form v-if="editForm" label-placement="left" label-width="80">
        <n-form-item label="用户名">
          <n-input v-model:value="editForm.username" />
        </n-form-item>
        <n-form-item label="邮箱">
          <n-input v-model:value="editForm.email" />
        </n-form-item>
        <n-form-item label="类型">
          <n-select v-model:value="editForm.account_type" :options="typeOptions" />
        </n-form-item>
        <n-form-item label="状态">
          <n-switch v-model:value="editForm.is_active" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showEdit = false">取消</n-button>
          <n-button type="primary" @click="submitEdit">保存基本信息</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 调整余额 -->
    <n-modal v-model:show="showBalance" preset="card" title="调整点数余额"
      style="width:min(520px,calc(100vw - 48px));max-height:calc(100vh - 48px)" content-style="overflow:auto">
      <template v-if="balanceForm">
        <n-alert type="info" :bordered="false" style="margin-bottom:16px">
          直接设置目标值（非增减）。当前：正式 {{ balanceForm.current_paid }} 点 /
          试用 {{ balanceForm.current_trial }} 点 / 赠送 {{ balanceForm.current_gift }} 点。至少填写一项。
        </n-alert>
        <n-form label-placement="left" label-width="100">
          <n-form-item label="正式点数">
            <n-input
              v-model:value="balanceForm.paid_credits"
              placeholder="留空则不修改，如 1000"
              :status="balanceError ? 'error' : undefined"
              style="font-family:var(--cy-font-mono)"
              clearable
            />
          </n-form-item>
          <n-form-item label="试用点数">
            <n-input
              v-model:value="balanceForm.trial_credits"
              placeholder="留空则不修改，如 500"
              :status="balanceError ? 'error' : undefined"
              style="font-family:var(--cy-font-mono)"
              clearable
            />
          </n-form-item>
          <n-form-item label="赠送点数">
            <n-input
              v-model:value="balanceForm.gift_credits"
              placeholder="留空则不修改，如 200"
              :status="balanceError ? 'error' : undefined"
              style="font-family:var(--cy-font-mono)"
              clearable
            />
          </n-form-item>
          <n-form-item label="备注">
            <n-input v-model:value="balanceForm.remark" placeholder="可选，将写入审计日志" />
          </n-form-item>
        </n-form>
        <div v-if="balanceError" style="color:var(--cy-danger);font-size:13px">{{ balanceError }}</div>
      </template>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showBalance = false">取消</n-button>
          <n-button type="primary" :loading="adjusting" @click="submitBalance">确认调整</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 分配 / 更换 Runtime Token -->
    <n-modal v-model:show="showAssign" preset="card" :title="detailUser?.runtime_token ? '更换 Runtime Token' : '分配 Runtime Token'"
      style="width:min(560px,calc(100vw - 48px));max-height:calc(100vh - 48px)" content-style="overflow:auto">
      <n-alert type="info" :bordered="false" style="margin-bottom:12px">
        从未分配 Token 中选择一枚绑定给该用户；旧 Token 将自动解绑回池。也可以留空选择，由系统自动挑选最旧的可用正式 Token。
      </n-alert>
      <n-spin :show="assignTokensLoading">
        <div v-if="availableTokens.length" class="assign-token-list">
          <div
            v-for="t in availableTokens"
            :key="t.id"
            class="assign-token-item"
            :class="{ active: assignSelectedId === t.id }"
            @click="assignSelectedId = assignSelectedId === t.id ? null : t.id"
          >
            <span class="assign-token-value">{{ t.token_value }}</span>
            <n-tag :type="t.is_trial ? 'warning' : 'info'" size="small" :bordered="false">
              {{ t.is_trial ? '试用' : '正式' }}
            </n-tag>
            <span class="assign-token-time">{{ formatTime(t.created_at) }}</span>
          </div>
        </div>
        <n-empty v-else description="没有可用 Token，请先在「Token 库存」录入" size="small" style="margin:12px 0" />
      </n-spin>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showAssign = false">取消</n-button>
          <n-button type="primary" :loading="assignSubmitting" @click="submitAssignToken">
            {{ assignSelectedId ? '绑定所选 Token' : '自动挑选并绑定' }}
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, h } from 'vue'
import { NTag, NButton, NSpace, useMessage, useDialog } from 'naive-ui'
import http from '../api/http'
import { formatTime } from '../utils/time'

const message = useMessage()
const dialog = useDialog()
const users = ref([])
const filterType = ref(null)
const filterStatus = ref(null)
const search = ref('')
const viewportWidth = ref(window.innerWidth)
const showDetail = ref(false)
const detailUser = ref(null)
const showEdit = ref(false)
const editForm = ref(null)
const editUserId = ref(null)
const showBalance = ref(false)
const balanceForm = ref(null)
const adjusting = ref(false)
const showAssign = ref(false)
const availableTokens = ref([])
const assignTokensLoading = ref(false)
const assignSelectedId = ref(null)
const assignSubmitting = ref(false)

const typeOptions = [
  { label: '试用', value: 'trial' },
  { label: '普通', value: 'normal' },
  { label: '付费', value: 'paid' },
]

const statusOptions = [
  { label: '正常', value: 'active' },
  { label: '禁用', value: 'disabled' },
  { label: '已归档', value: 'archived' },
]

const typeTag = { trial: 'warning', paid: 'success', normal: 'default' }
const typeLabel = { trial: '试用', paid: '付费', normal: '普通' }

// 金额格式化：字符串 Decimal → 按需保留小数
function fmt(v, digits) {
  const n = Number(v)
  if (!isFinite(n)) return '0.00'
  return n.toFixed(digits)
}

const filtered = computed(() => {
  let list = users.value
  if (filterType.value) list = list.filter(u => u.account_type === filterType.value)
  if (filterStatus.value === 'active') list = list.filter(u => u.is_active && !u.archived_at)
  if (filterStatus.value === 'disabled') list = list.filter(u => !u.is_active && !u.archived_at)
  if (filterStatus.value === 'archived') list = list.filter(u => !!u.archived_at)
  if (search.value) {
    const q = search.value.toLowerCase()
    list = list.filter(u =>
      (u.username || '').toLowerCase().includes(q) ||
      (u.email || '').toLowerCase().includes(q)
    )
  }
  return list
})

const allColumns = [
  { title: '#', key: 'index', width: 50, render: (_, index) => index + 1 },
  { title: '用户名', key: 'username', width: 130 },
  { title: '邮箱', key: 'email', width: 200, ellipsis: true },
  {
    title: '点数余额', key: 'total_credits', width: 110,
    render: row => h('span', { style: 'font-family:var(--cy-font-mono);color:var(--cy-text);font-weight:600' },
      `${row.total_credits ?? 0}`),
  },
  {
    title: '正式', key: 'paid_credits', width: 80,
    render: row => h('span', { style: 'font-family:var(--cy-font-mono)' }, `${row.paid_credits ?? 0}`),
  },
  {
    title: '试用', key: 'trial_credits', width: 80,
    render: row => h('span', { style: 'font-family:var(--cy-font-mono);color:var(--cy-warning)' }, `${row.trial_credits ?? 0}`),
  },
  {
    title: '赠送', key: 'gift_credits', width: 80,
    render: row => h('span', { style: 'font-family:var(--cy-font-mono);color:#6366f1' }, `${row.gift_credits ?? 0}`),
  },
  {
    title: '类型', key: 'account_type', width: 80,
    render: row => h(NTag, { type: typeTag[row.account_type] || 'default', size: 'small', bordered: false },
      { default: () => typeLabel[row.account_type] || row.account_type }),
  },
  {
    title: '状态', key: 'is_active', width: 80,
    render: row => h(NTag, {
      type: row.archived_at ? 'default' : (row.is_active ? 'success' : 'error'),
      size: 'small', bordered: false,
    }, { default: () => row.archived_at ? '已归档' : (row.is_active ? '正常' : '禁用') }),
  },
  {
    title: '注册时间', key: 'created_at', width: 160,
    render: row => formatTime(row.created_at),
  },
  {
    title: '操作', key: 'actions', width: 250, fixed: 'right',
    render: row => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'small', quaternary: true, type: 'info', onClick: () => viewUser(row) }, { default: () => '查看' }),
        h(NButton, { size: 'small', quaternary: true, type: 'warning', disabled: !!row.archived_at, onClick: () => openEdit(row) }, { default: () => '编辑' }),
        h(NButton, { size: 'small', quaternary: true, type: 'primary', disabled: !!row.archived_at, onClick: () => openBalance(row) }, { default: () => '调余额' }),
        h(NButton, { size: 'small', quaternary: true, type: 'error', disabled: !!row.archived_at, onClick: () => confirmDelete(row) }, { default: () => row.archived_at ? '已归档' : '删除' }),
      ]
    }),
  },
]

const compactColumnKeys = new Set(['index', 'username', 'email', 'total_credits', 'account_type', 'is_active', 'actions'])
const columns = computed(() => viewportWidth.value >= 1600
  ? allColumns
  : allColumns.filter(column => compactColumnKeys.has(column.key)))
const tableScrollX = computed(() => viewportWidth.value >= 1600 ? 1300 : 900)

const usageColumns = [
  { title: '模型', key: 'model', width: 120 },
  { title: '类型', key: 'usage_type', width: 90 },
  { title: '图片数', key: 'image_count', width: 70 },
  {
    title: '单价（点）', key: 'unit_credits', width: 90,
    render: row => row.unit_credits != null ? `${row.unit_credits}` : '-',
  },
  {
    title: '费用（点）', key: 'cost_credits', width: 100,
    render: row => `${row.cost_credits ?? 0}`,
  },
  { title: '时间', key: 'created_at', width: 160, render: row => formatTime(row.created_at) },
]

async function loadUsers() {
  try {
    const { data } = await http.get('/api/admin/users')
    users.value = data
  } catch (e) {
    message.error(e.response?.data?.detail || '加载用户失败')
  }
}

// 5xx 时后端 detail 是通用文案，仍避免把任何内部信息弹给管理员
function apiError(e, fallback) {
  return e.response?.status && e.response.status >= 500 ? fallback : (e.response?.data?.detail || fallback)
}

async function viewUser(row) {
  try {
    const { data } = await http.get(`/api/admin/users/${row.id}`)
    detailUser.value = data
    showDetail.value = true
  } catch (e) {
    message.error(apiError(e, '获取用户详情失败，请稍后重试'))
  }
}

async function openEdit(row) {
  try {
    const { data } = await http.get(`/api/admin/users/${row.id}`)
    editUserId.value = row.id
    editForm.value = {
      username: data.username,
      email: data.email,
      account_type: data.account_type,
      is_active: data.is_active,
    }
    showEdit.value = true
  } catch (e) {
    message.error(apiError(e, '获取用户详情失败，请稍后重试'))
  }
}

async function submitEdit() {
  try {
    await http.put(`/api/admin/users/${editUserId.value}`, editForm.value)
    message.success('保存成功')
    showEdit.value = false
    await loadUsers()
  } catch (e) {
    message.error(e.response?.data?.detail || '保存失败')
  }
}

// 校验调账输入：至少一项；数字 ≥ 0 且最多 6 位小数（字符串原样传）
const balanceError = computed(() => {
  const f = balanceForm.value
  if (!f) return null
  const check = (v, label) => {
    const raw = (v ?? '').trim()
    if (!raw) return null
    if (!/^\d+$/.test(raw)) return `${label}必须为非负整数（CY 点）`
    return null
  }
  const paid = (f.paid_credits ?? '').trim()
  const trial = (f.trial_credits ?? '').trim()
  const gift = (f.gift_credits ?? '').trim()
  if (!paid && !trial && !gift) return '请至少填写一项（正式/试用/赠送点数）'
  return check(f.paid_credits, '正式点数') || check(f.trial_credits, '试用点数') || check(f.gift_credits, '赠送点数')
})

function openBalance(row) {
  // 兼容列表行与详情对象
  balanceForm.value = {
    userId: row.id,
    username: row.username,
    current_paid: row.paid_credits ?? 0,
    current_trial: row.trial_credits ?? 0,
    current_gift: row.gift_credits ?? 0,
    paid_credits: '',
    trial_credits: '',
    gift_credits: '',
    remark: '',
  }
  showBalance.value = true
}

async function submitBalance() {
  const f = balanceForm.value
  if (balanceError.value) { message.warning(balanceError.value); return }
  const body = { remark: f.remark || '' }
  if ((f.paid_credits ?? '').trim()) body.paid_credits = Number(f.paid_credits.trim())
  if ((f.trial_credits ?? '').trim()) body.trial_credits = Number(f.trial_credits.trim())
  if ((f.gift_credits ?? '').trim()) body.gift_credits = Number(f.gift_credits.trim())

  adjusting.value = true
  try {
    const { data } = await http.put(`/api/admin/users/${f.userId}/balance`, body)
    message.success(`调整成功：正式 ${data.paid_credits} 点，试用 ${data.trial_credits} 点，赠送 ${data.gift_credits} 点`)
    showBalance.value = false
    if (showDetail.value && detailUser.value && detailUser.value.id === f.userId) {
      await viewUser({ id: f.userId })
    }
    await loadUsers()
  } catch (e) {
    message.error(e.response?.data?.detail || '调整失败')
  } finally {
    adjusting.value = false
  }
}

// ── Runtime Token 分配 / 更换 / 解绑 ──────────────────────────

const releaseLoading = ref(false)

async function openAssignToken() {
  if (!detailUser.value) return
  showAssign.value = true
  assignSelectedId.value = null
  assignTokensLoading.value = true
  try {
    const { data } = await http.get('/api/admin/tokens', {
      params: { status: 'active', page: 1, page_size: 200 },
    })
    availableTokens.value = (data.tokens || []).filter(t => t.status === 'active')
  } catch (e) {
    message.error(e.response?.data?.detail || '加载可用 Token 失败')
  } finally {
    assignTokensLoading.value = false
  }
}

async function releaseToken() {
  if (!detailUser.value) return
  releaseLoading.value = true
  try {
    await http.post(`/api/admin/users/${detailUser.value.id}/runtime-token/release`)
    message.success('已解除绑定')
    await viewUser({ id: detailUser.value.id })
  } catch (e) {
    message.error(e.response?.data?.detail || '解绑失败')
  } finally {
    releaseLoading.value = false
  }
}

async function submitAssignToken() {
  if (!detailUser.value) return
  assignSubmitting.value = true
  try {
    const body = assignSelectedId.value ? { token_id: assignSelectedId.value } : {}
    const { data } = await http.post(
      `/api/admin/users/${detailUser.value.id}/runtime-token/assign`, body,
    )
    message.success(`已绑定 Token ${data.runtime_token.masked_token}`)
    showAssign.value = false
    await viewUser({ id: detailUser.value.id })  // 刷新详情中的 runtime_token
  } catch (e) {
    const detail = e.response?.data?.detail
    if (detail && typeof detail === 'object' && detail.code === 'NO_AVAILABLE_RUNTIME_TOKEN') {
      message.error(detail.message || 'Token 库存中没有可用 Token')
    } else if (typeof detail === 'string') {
      message.error(detail)
    } else {
      message.error('分配失败')
    }
  } finally {
    assignSubmitting.value = false
  }
}

async function confirmDelete(row) {
  let preview
  try {
    const response = await http.get(`/api/admin/users/${row.id}/deletion-preview`)
    preview = response.data
  } catch (e) {
    message.error(apiError(e, '无法检查账户关联数据，请稍后重试'))
    return
  }

  const isArchive = preview.mode === 'archive'
  const blockerLabels = {
    orders: '订单', refund_requests: '退款', billing_transactions: '账务流水',
    usage_logs: '用量记录', cost_margin_ledger: '成本记录',
  }
  const blockerText = Object.entries(preview.blockers || {})
    .filter(([, count]) => count > 0)
    .map(([key, count]) => `${blockerLabels[key] || key} ${count} 条`)
    .join('、')

  dialog.warning({
    title: isArchive ? '归档客户账户' : '彻底删除空账户',
    content: isArchive
      ? `账户“${row.username}”存在业务历史（${blockerText}），将改为归档：禁止登录并解除 Token 绑定，历史数据继续保留。`
      : `账户“${row.username}”没有业务历史，将彻底删除账户及设备、Token 绑定。试用领取与分配审计仍会保留。`,
    positiveText: isArchive ? '确认归档' : '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        if (isArchive) {
          await http.post(`/api/admin/users/${row.id}/archive`, { reason: '管理员从客户账户列表归档' })
          message.success('账户已归档，业务历史已保留')
        } else {
          await http.delete(`/api/admin/users/${row.id}`)
          message.success('空账户已彻底删除')
        }
        await loadUsers()
      } catch (e) {
        const detail = e.response?.data?.detail
        message.error(typeof detail === 'object' ? (detail.message || '操作失败') : (detail || '操作失败'))
      }
    },
  })
}

function syncViewport() { viewportWidth.value = window.innerWidth }

onMounted(() => {
  window.addEventListener('resize', syncViewport)
  loadUsers()
})
onBeforeUnmount(() => window.removeEventListener('resize', syncViewport))
</script>

<style scoped>
.runtime-token-box {
  background: var(--cy-bg-surface);
  border: 1px solid var(--cy-border-light);
  border-radius: var(--cy-radius);
  padding: 14px 16px;
}

.runtime-token-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.runtime-token-row.sub {
  margin-bottom: 12px;
}

.runtime-token-label {
  font-size: 12px;
  color: var(--cy-text-muted);
  min-width: 88px;
}

.runtime-token-value {
  font-family: var(--cy-font-mono);
  font-size: 13px;
  color: var(--cy-text);
}

.runtime-token-empty {
  font-size: 13px;
  color: var(--cy-text-muted);
  margin: 0 0 12px;
}

.assign-token-list {
  max-height: 280px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.assign-token-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--cy-border-light);
  border-radius: var(--cy-radius);
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.assign-token-item:hover {
  border-color: var(--cy-primary, #00d4aa);
}

.assign-token-item.active {
  border-color: var(--cy-primary, #00d4aa);
  background: rgba(0, 212, 170, 0.08);
}

.assign-token-value {
  font-family: var(--cy-font-mono);
  font-size: 12px;
  flex: 1;
}

.assign-token-time {
  font-size: 11px;
  color: var(--cy-text-muted);
}

.detail-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

@media (max-width: 768px) {
  .detail-stats {
    grid-template-columns: repeat(2, 1fr);
  }
}

.detail-stats .stat-card {
  position: relative;
  background: var(--cy-bg-surface);
  border: 1px solid var(--cy-border-light);
  border-radius: var(--cy-radius);
  padding: 14px 16px;
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
  font-size: 12px;
  color: var(--cy-text-muted);
  margin-bottom: 4px;
}

.stat-card-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--cy-text);
  font-family: var(--cy-font-mono);
}
</style>
