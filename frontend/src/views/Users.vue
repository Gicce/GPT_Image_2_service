<template>
  <div>
    <n-h2>用户列表</n-h2>
    <div style="display:flex;gap:12px;margin-bottom:16px">
      <n-select v-model:value="filterType" :options="typeOptions" clearable placeholder="筛选类型" style="width:160px" />
      <n-input v-model:value="search" placeholder="搜索用户名 / 邮箱" style="width:260px" clearable />
    </div>
    <n-data-table :columns="columns" :data="filtered" :pagination="{ pageSize: 20 }" :row-key="row => row.id" />

    <!-- 查看用户详情 -->
    <n-modal v-model:show="showDetail" preset="card" title="用户详情" style="width:660px">
      <template v-if="detailUser">
        <n-descriptions :column="2" bordered label-placement="left" size="small">
          <n-descriptions-item label="用户名">{{ detailUser.username }}</n-descriptions-item>
          <n-descriptions-item label="邮箱">{{ detailUser.email }}</n-descriptions-item>
          <n-descriptions-item label="类型">
            <n-tag :type="typeTag[detailUser.account_type] || 'default'" size="small">{{ typeLabel[detailUser.account_type] || detailUser.account_type }}</n-tag>
          </n-descriptions-item>
          <n-descriptions-item label="状态">
            <n-tag :type="detailUser.is_active ? 'success' : 'error'" size="small">{{ detailUser.is_active ? '正常' : '禁用' }}</n-tag>
          </n-descriptions-item>
          <n-descriptions-item label="注册时间">{{ formatTime(detailUser.created_at) }}</n-descriptions-item>
          <n-descriptions-item label="试用到期">{{ detailUser.trial_expires_at ? formatTime(detailUser.trial_expires_at) : '-' }}</n-descriptions-item>
        </n-descriptions>

        <n-divider style="margin:16px 0 12px">Token & 余额</n-divider>
        <n-grid :cols="2" :x-gap="12" :y-gap="12">
          <n-gi v-for="t in (detailUser.tokens || [])" :key="t.group">
            <n-card size="small" :bordered="true">
              <n-statistic :label="t.group + (t.is_trial ? ' (试用)' : '')">
                <template #prefix>$</template>
                {{ Number(t.balance_usd).toFixed(4) }}
              </n-statistic>
              <div v-if="t.api_token" style="margin-top:8px;font-size:12px;color:#666">
                <n-input-group style="margin-top:4px">
                  <n-input :value="t.api_token" readonly size="small" style="font-family:monospace;font-size:12px" />
                  <n-button size="small" type="primary" @click="copyToken(t.api_token)">复制</n-button>
                </n-input-group>
              </div>
            </n-card>
          </n-gi>
          <n-gi v-if="!(detailUser.tokens && detailUser.tokens.length)">
            <n-empty description="暂无 Token" size="small" />
          </n-gi>
        </n-grid>

        <n-divider style="margin:16px 0 12px">最近用量</n-divider>
        <n-data-table v-if="detailUser.usage_logs && detailUser.usage_logs.length" :columns="usageColumns" :data="detailUser.usage_logs" :pagination="{ pageSize: 10 }" size="small" :max-height="240" />
        <n-empty v-else description="暂无用量记录" size="small" />
      </template>
    </n-modal>

    <!-- 编辑用户 -->
    <n-modal v-model:show="showEdit" preset="card" title="编辑用户" style="width:600px">
      <n-form v-if="editForm" label-placement="left" label-width="80">
        <n-form-item label="用户名">
          <n-input v-model:value="editForm.username" />
        </n-form-item>
        <n-form-item label="邮箱">
          <n-input v-model:value="editForm.email" />
        </n-form-item>
        <n-form-item label="类型">
          <n-select v-model:value="editForm.account_type" :options="allTypeOptions" />
        </n-form-item>
        <n-form-item label="状态">
          <n-switch v-model:value="editForm.is_active" />
        </n-form-item>
      </n-form>
      <n-divider style="margin:12px 0">Token 管理</n-divider>
      <div v-for="t in editTokens" :key="t.group" style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <n-tag size="small">{{ t.group }}</n-tag>
        <span style="font-family:monospace;font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ t.api_token || '-' }}</span>
        <span style="white-space:nowrap">${{ Number(t.balance_usd).toFixed(2) }}</span>
        <n-button size="tiny" type="warning" @click="openTokenEdit(t)">编辑</n-button>
        <n-button size="tiny" type="error" @click="deleteToken(t)">删除</n-button>
      </div>
      <n-empty v-if="!editTokens.length" description="暂无 Token" size="small" style="margin:8px 0" />
      <n-button size="small" dashed @click="openTokenAdd">+ 添加分组 Token</n-button>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showEdit = false">取消</n-button>
          <n-button type="primary" @click="submitEdit">保存基本信息</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- Token 编辑/添加弹窗 -->
    <n-modal v-model:show="showTokenForm" preset="card" :title="tokenFormEdit ? '编辑 Token' : '添加 Token'" style="width:420px">
      <n-form label-placement="left" label-width="60">
        <n-form-item label="分组">
          <n-select v-model:value="tokenForm.group" :options="groupOptions" :disabled="tokenFormEdit" tag filterable placeholder="选择分组" />
        </n-form-item>
        <n-form-item label="Token">
          <n-input v-model:value="tokenForm.token_value" placeholder="sk-xxx" />
        </n-form-item>
        <n-form-item label="余额($)">
          <n-input-number v-model:value="tokenForm.balance_usd" :precision="4" :min="0" style="width:100%" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showTokenForm=false">取消</n-button>
          <n-button type="primary" @click="submitToken">确认</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { NTag, NButton, NSpace, useMessage, useDialog } from 'naive-ui'
import http from '../api/http'

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
const editTokens = ref([])
const showTokenForm = ref(false)
const tokenForm = ref({ group: null, token_value: '', balance_usd: 0 })
const tokenFormEdit = ref(false)
const groupOptions = ref([])

const typeOptions = [
  { label: '试用', value: 'trial' },
  { label: '普通', value: 'normal' },
  { label: '付费', value: 'paid' },
]
const allTypeOptions = [
  { label: '试用', value: 'trial' },
  { label: '普通', value: 'normal' },
  { label: '付费', value: 'paid' },
]

const typeTag = { trial: 'warning', paid: 'success', normal: 'default' }
const typeLabel = { trial: '试用', paid: '付费', normal: '普通' }

function formatTime(iso) {
  if (!iso) return '-'
  return iso.replace('T', ' ').slice(0, 19)
}

function copyToken(token) {
  navigator.clipboard.writeText(token).then(
    () => message.success('已复制到剪贴板'),
    () => message.error('复制失败')
  )
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
  { title: '用户名', key: 'username', width: 140 },
  { title: '邮箱', key: 'email', width: 200 },
  { title: '类型', key: 'account_type', width: 80,
    render: row => h(NTag, { type: typeTag[row.account_type] || 'default', size: 'small' },
      { default: () => typeLabel[row.account_type] || row.account_type }) },
  { title: '余额', key: 'tokens', width: 160,
    render: row => {
      const tokens = row.tokens || []
      if (!tokens.length) return '-'
      return h('div', null, tokens.map(t =>
        h('span', { style: 'margin-right:8px' }, `${t.group}: $${Number(t.balance_usd).toFixed(2)}`)
      ))
    }
  },
  { title: '状态', key: 'is_active', width: 80,
    render: row => h(NTag, { type: row.is_active ? 'success' : 'error', size: 'small' },
      { default: () => row.is_active ? '正常' : '禁用' }) },
  { title: '注册时间', key: 'created_at', width: 160,
    render: row => row.created_at?.replace('T', ' ').slice(0, 19) },
  { title: '操作', key: 'actions', width: 200,
    render: row => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'small', quaternary: true, type: 'info', onClick: () => viewUser(row) }, { default: () => '查看' }),
        h(NButton, { size: 'small', quaternary: true, type: 'warning', onClick: () => openEdit(row) }, { default: () => '编辑' }),
        h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => confirmDelete(row) }, { default: () => '删除' }),
      ]
    })
  },
]

const usageColumns = [
  { title: '模型', key: 'model', width: 120 },
  { title: '类型', key: 'usage_type', width: 80 },
  { title: '费用($)', key: 'cost_usd', width: 100, render: row => `$${Number(row.cost_usd).toFixed(4)}` },
  { title: '时间', key: 'created_at', width: 160, render: row => row.created_at?.replace('T', ' ').slice(0, 19) },
]

async function loadUsers() {
  const { data } = await http.get('/api/admin/users')
  users.value = data
}

async function viewUser(row) {
  const { data } = await http.get(`/api/admin/users/${row.id}`)
  detailUser.value = data
  showDetail.value = true
}

async function openEdit(row) {
  editUserId.value = row.id
  const { data } = await http.get(`/api/admin/users/${row.id}`)
  editForm.value = {
    username: data.username,
    email: data.email,
    account_type: data.account_type,
    is_active: data.is_active,
  }
  editTokens.value = data.tokens || []
  try {
    const { data: groups } = await http.get('/api/admin/groups')
    groupOptions.value = groups.map(g => ({ label: g.name, value: g.name }))
  } catch {}
  showEdit.value = true
}

function openTokenEdit(t) {
  tokenFormEdit.value = true
  tokenForm.value = { group: t.group, token_value: t.api_token || '', balance_usd: Number(t.balance_usd) }
  showTokenForm.value = true
}

function openTokenAdd() {
  tokenFormEdit.value = false
  tokenForm.value = { group: null, token_value: '', balance_usd: 0 }
  showTokenForm.value = true
}

async function submitToken() {
  const { group, token_value, balance_usd } = tokenForm.value
  if (!group) { message.warning('请选择分组'); return }
  if (!token_value) { message.warning('请输入 Token'); return }
  try {
    await http.post(`/api/admin/users/${editUserId.value}/tokens`, { group, token_value, balance_usd })
    message.success('保存成功')
    showTokenForm.value = false
    const { data } = await http.get(`/api/admin/users/${editUserId.value}`)
    editTokens.value = data.tokens || []
    await loadUsers()
  } catch (e) {
    message.error(e.response?.data?.detail || '操作失败')
  }
}

function deleteToken(t) {
  dialog.warning({
    title: '确认删除',
    content: `确定删除 ${t.group} 分组的 Token 吗？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await http.delete(`/api/admin/users/${editUserId.value}/tokens/${t.group}`)
        message.success('已删除')
        editTokens.value = editTokens.value.filter(x => x.group !== t.group)
        await loadUsers()
      } catch (e) {
        message.error(e.response?.data?.detail || '删除失败')
      }
    }
  })
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
    }
  })
}

onMounted(loadUsers)
</script>
