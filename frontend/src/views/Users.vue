<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">客户账户</h2>
        <p class="page-header-subtitle">统一余额体系：现金余额 + 试用额度（USD）</p>
      </div>
    </div>

    <div class="filter-bar">
      <n-select v-model:value="filterType" :options="typeOptions" clearable placeholder="筛选类型" style="width:160px" />
      <n-input v-model:value="search" placeholder="搜索用户名 / 邮箱" style="width:260px" clearable />
    </div>

    <n-data-table
      :columns="columns"
      :data="filtered"
      :pagination="{ pageSize: 20 }"
      :row-key="row => row.id"
      :bordered="false"
    />

    <!-- 查看用户详情 -->
    <n-modal v-model:show="showDetail" preset="card" title="用户详情" style="width:720px">
      <template v-if="detailUser">
        <n-descriptions :column="2" bordered label-placement="left" size="small">
          <n-descriptions-item label="用户名">{{ detailUser.username }}</n-descriptions-item>
          <n-descriptions-item label="邮箱">{{ detailUser.email }}</n-descriptions-item>
          <n-descriptions-item label="类型">
            <n-tag :type="typeTag[detailUser.account_type] || 'default'" size="small" :bordered="false">
              {{ typeLabel[detailUser.account_type] || detailUser.account_type }}
            </n-tag>
          </n-descriptions-item>
          <n-descriptions-item label="状态">
            <n-tag :type="detailUser.is_active ? 'success' : 'error'" size="small" :bordered="false">
              {{ detailUser.is_active ? '正常' : '禁用' }}
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
          <n-button size="small" type="primary" secondary :loading="assignLoading" @click="openAssignToken">
            {{ detailUser.runtime_token ? '更换 Token' : '分配 Token' }}
          </n-button>
        </div>

        <n-divider style="margin:16px 0 12px">余额与消费</n-divider>
        <div class="detail-stats">
          <div class="stat-card">
            <div class="stat-card-accent" style="background:linear-gradient(90deg,#00d4aa,#00d4aa00)"></div>
            <div class="stat-card-label">现金余额</div>
            <div class="stat-card-value">${{ fmt(detailUser.balance_usd, 4) }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-card-accent" style="background:linear-gradient(90deg,#f59e0b,#f59e0b00)"></div>
            <div class="stat-card-label">试用额度</div>
            <div class="stat-card-value">${{ fmt(detailUser.trial_credit_usd, 4) }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-card-accent" style="background:linear-gradient(90deg,#3b82f6,#3b82f600)"></div>
            <div class="stat-card-label">累计充值</div>
            <div class="stat-card-value">${{ fmt(detailUser.total_recharged_usd, 2) }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-card-accent" style="background:linear-gradient(90deg,#ec4899,#ec489900)"></div>
            <div class="stat-card-label">累计消费</div>
            <div class="stat-card-value">${{ fmt(detailUser.total_spent_usd, 4) }}</div>
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
    <n-modal v-model:show="showEdit" preset="card" title="编辑用户" style="width:560px">
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
    <n-modal v-model:show="showBalance" preset="card" title="调整余额" style="width:520px">
      <template v-if="balanceForm">
        <n-alert type="info" :bordered="false" style="margin-bottom:16px">
          直接设置目标值（非增减）。当前：现金余额 ${{ fmt(balanceForm.current_balance, 4) }}，
          试用额度 ${{ fmt(balanceForm.current_trial, 4) }}。至少填写一项。
        </n-alert>
        <n-form label-placement="left" label-width="100">
          <n-form-item label="现金余额 ($)">
            <n-input
              v-model:value="balanceForm.balance_usd"
              placeholder="留空则不修改，如 10.5"
              :status="balanceError ? 'error' : undefined"
              style="font-family:var(--cy-font-mono)"
              clearable
            />
          </n-form-item>
          <n-form-item label="试用额度 ($)">
            <n-input
              v-model:value="balanceForm.trial_credit_usd"
              placeholder="留空则不修改，如 0.14"
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
    <n-modal v-model:show="showAssign" preset="card" :title="detailUser?.runtime_token ? '更换 Runtime Token' : '分配 Runtime Token'" style="width:560px">
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
import { ref, computed, onMounted, h } from 'vue'
import { NTag, NButton, NSpace, useMessage, useDialog } from 'naive-ui'
import http from '../api/http'
import { formatTime } from '../utils/time'

const message = useMessage()
const dialog = useDialog()
const users = ref([])
const filterType = ref(null)
const search = ref('')
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
  { title: '#', key: 'index', width: 50, render: (_, index) => index + 1 },
  { title: '用户名', key: 'username', width: 130 },
  { title: '邮箱', key: 'email', width: 200, ellipsis: true },
  {
    title: '余额', key: 'balance_usd', width: 110,
    render: row => h('span', { style: 'font-family:var(--cy-font-mono);color:var(--cy-text)' },
      `$${fmt(row.balance_usd, 2)}`),
  },
  {
    title: '试用额度', key: 'trial_credit_usd', width: 100,
    render: row => h('span', { style: 'font-family:var(--cy-font-mono);color:var(--cy-warning)' },
      `$${fmt(row.trial_credit_usd, 2)}`),
  },
  {
    title: '类型', key: 'account_type', width: 80,
    render: row => h(NTag, { type: typeTag[row.account_type] || 'default', size: 'small', bordered: false },
      { default: () => typeLabel[row.account_type] || row.account_type }),
  },
  {
    title: '状态', key: 'is_active', width: 80,
    render: row => h(NTag, { type: row.is_active ? 'success' : 'error', size: 'small', bordered: false },
      { default: () => row.is_active ? '正常' : '禁用' }),
  },
  {
    title: '注册时间', key: 'created_at', width: 160,
    render: row => formatTime(row.created_at),
  },
  {
    title: '操作', key: 'actions', width: 250,
    render: row => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'small', quaternary: true, type: 'info', onClick: () => viewUser(row) }, { default: () => '查看' }),
        h(NButton, { size: 'small', quaternary: true, type: 'warning', onClick: () => openEdit(row) }, { default: () => '编辑' }),
        h(NButton, { size: 'small', quaternary: true, type: 'primary', onClick: () => openBalance(row) }, { default: () => '调余额' }),
        h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => confirmDelete(row) }, { default: () => '删除' }),
      ]
    }),
  },
]

const usageColumns = [
  { title: '模型', key: 'model', width: 120 },
  { title: '类型', key: 'usage_type', width: 90 },
  { title: '图片数', key: 'image_count', width: 70 },
  {
    title: '单价 ($)', key: 'unit_price', width: 90,
    render: row => row.unit_price != null ? `$${fmt(row.unit_price, 4)}` : '-',
  },
  {
    title: '费用 ($)', key: 'cost_usd', width: 100,
    render: row => `$${fmt(row.cost_usd, 4)}`,
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

async function viewUser(row) {
  try {
    const { data } = await http.get(`/api/admin/users/${row.id}`)
    detailUser.value = data
    showDetail.value = true
  } catch (e) {
    message.error(e.response?.data?.detail || '加载用户详情失败')
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
    message.error(e.response?.data?.detail || '加载用户失败')
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
    if (!/^\d+(\.\d{1,6})?$/.test(raw)) return `${label}必须为非负数字，最多 6 位小数`
    return null
  }
  const cash = (f.balance_usd ?? '').trim()
  const trial = (f.trial_credit_usd ?? '').trim()
  if (!cash && !trial) return '请至少填写一项（现金余额或试用额度）'
  return check(f.balance_usd, '现金余额') || check(f.trial_credit_usd, '试用额度')
})

function openBalance(row) {
  // 兼容列表行与详情对象
  balanceForm.value = {
    userId: row.id,
    username: row.username,
    current_balance: row.balance_usd,
    current_trial: row.trial_credit_usd,
    balance_usd: '',
    trial_credit_usd: '',
    remark: '',
  }
  showBalance.value = true
}

async function submitBalance() {
  const f = balanceForm.value
  if (balanceError.value) { message.warning(balanceError.value); return }
  const body = { remark: f.remark || '' }
  if ((f.balance_usd ?? '').trim()) body.balance_usd = f.balance_usd.trim()
  if ((f.trial_credit_usd ?? '').trim()) body.trial_credit_usd = f.trial_credit_usd.trim()

  adjusting.value = true
  try {
    const { data } = await http.put(`/api/admin/users/${f.userId}/balance`, body)
    message.success(`调整成功：现金余额 $${fmt(data.balance_usd, 2)}，试用额度 $${fmt(data.trial_credit_usd, 2)}`)
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

// ── Runtime Token 分配 / 更换 ──────────────────────────────

async function openAssignToken() {
  if (!detailUser.value) return
  showAssign.value = true
  assignSelectedId.value = null
  assignTokensLoading.value = true
  try {
    const { data } = await http.get('/api/admin/tokens', {
      params: { is_assigned: false, page: 1, page_size: 100 },
    })
    availableTokens.value = (data.tokens || []).filter(t => !t.is_disabled)
  } catch (e) {
    message.error(e.response?.data?.detail || '加载可用 Token 失败')
  } finally {
    assignTokensLoading.value = false
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

function confirmDelete(row) {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除用户 "${row.username}" 吗？此操作不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await http.delete(`/api/admin/users/${row.id}`)
        message.success('已删除')
        await loadUsers()
      } catch (e) {
        message.error(e.response?.data?.detail || '删除失败')
      }
    },
  })
}

onMounted(loadUsers)
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
