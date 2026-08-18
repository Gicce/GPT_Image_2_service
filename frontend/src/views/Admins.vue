<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">管理员管理</h2>
        <p class="page-header-subtitle">可以登录 CyCloudHub 后台的管理员账户（与客户账户严格隔离）</p>
      </div>
      <n-button type="primary" @click="showCreate = true">+ 新建管理员</n-button>
    </div>

    <n-data-table
      :columns="columns"
      :data="admins"
      :loading="loading"
      :row-key="row => row.id"
      :bordered="false"
    />

    <!-- 新建管理员 -->
    <n-modal v-model:show="showCreate" preset="card" title="新建管理员" style="width:480px">
      <n-form label-placement="top">
        <n-form-item label="用户名" required>
          <n-input v-model:value="createForm.username" placeholder="3-64 位，不区分大小写" />
        </n-form-item>
        <n-form-item label="显示名称">
          <n-input v-model:value="createForm.display_name" placeholder="可选" />
        </n-form-item>
        <n-form-item label="密码" required>
          <n-input v-model:value="createForm.password" type="password" show-password-on="click"
                   placeholder="至少 10 位，建议使用密码管理器生成" />
        </n-form-item>
        <n-form-item label="角色" required>
          <n-radio-group v-model:value="createForm.role">
            <n-radio value="admin">admin（日常运营）</n-radio>
            <n-radio value="super_admin">super_admin（完全权限）</n-radio>
          </n-radio-group>
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showCreate = false">取消</n-button>
          <n-button type="primary" :loading="creating" :disabled="!createForm.username || !createForm.password" @click="createAdmin">
            创建
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 编辑管理员 -->
    <n-modal v-model:show="showEdit" preset="card" title="编辑管理员" style="width:480px">
      <n-form label-placement="top">
        <n-form-item label="用户名" required>
          <n-input v-model:value="editForm.username" />
        </n-form-item>
        <n-form-item label="显示名称">
          <n-input v-model:value="editForm.display_name" />
        </n-form-item>
        <n-form-item label="角色">
          <n-radio-group v-model:value="editForm.role">
            <n-radio value="admin">admin</n-radio>
            <n-radio value="super_admin">super_admin</n-radio>
          </n-radio-group>
        </n-form-item>
        <n-form-item label="状态">
          <n-switch v-model:value="editForm.is_active">
            <template #checked>启用</template>
            <template #unchecked>禁用</template>
          </n-switch>
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showEdit = false">取消</n-button>
          <n-button type="primary" :loading="editing" @click="saveEdit">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 重置密码 -->
    <n-modal v-model:show="showReset" preset="card" title="重置管理员密码" style="width:480px">
      <n-alert type="warning" :bordered="false" style="margin-bottom:16px">
        将为管理员 <strong>{{ resetTarget ? (resetTarget.display_name || resetTarget.username) : '' }}</strong> 设置新密码：其旧密码立即失效，且下次登录后需先修改密码。
      </n-alert>
      <n-form label-placement="top">
        <n-form-item label="新密码" required>
          <n-input v-model:value="resetForm.new_password" type="password" show-password-on="click"
                   placeholder="至少 10 位" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showReset = false">取消</n-button>
          <n-button type="warning" :loading="resetting" :disabled="!resetForm.new_password" @click="doReset">
            重置密码
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { h, onMounted, ref } from 'vue'
import { useMessage, NButton, NSpace, NTag, NPopconfirm } from 'naive-ui'
import http from '../api/http'

const msg = useMessage()
const admins = ref([])
const loading = ref(false)

const showCreate = ref(false)
const creating = ref(false)
const createForm = ref({ username: '', display_name: '', password: '', role: 'admin' })

const showEdit = ref(false)
const editing = ref(false)
const editTarget = ref(null)
const editForm = ref({ username: '', display_name: '', role: 'admin', is_active: true })

const showReset = ref(false)
const resetting = ref(false)
const resetTarget = ref(null)
const resetForm = ref({ new_password: '' })

const roleLabel = { super_admin: 'super_admin', admin: 'admin' }
const roleTag = { super_admin: 'warning', admin: 'info' }

function formatTime(iso) {
  if (!iso) return '-'
  try { return new Date(iso).toLocaleString('zh-CN', { hour12: false }) } catch { return iso }
}

const columns = [
  { title: '用户名', key: 'username', width: 140 },
  { title: '显示名称', key: 'display_name', width: 140, render: row => row.display_name || '-' },
  {
    title: '角色', key: 'role', width: 120,
    render: row => h(NTag, { type: roleTag[row.role] || 'default', size: 'small', bordered: false },
      { default: () => roleLabel[row.role] || row.role }),
  },
  {
    title: '状态', key: 'is_active', width: 80,
    render: row => h(NTag, { type: row.is_active ? 'success' : 'error', size: 'small', bordered: false },
      { default: () => row.is_active ? '启用' : '禁用' }),
  },
  { title: '最后登录', key: 'last_login_at', width: 170, render: row => formatTime(row.last_login_at) },
  { title: '创建时间', key: 'created_at', width: 170, render: row => formatTime(row.created_at) },
  {
    title: '操作', key: 'actions', width: 240,
    render(row) {
      return h(NSpace, { size: 'small' }, {
        default: () => [
          h(NButton, { size: 'tiny', secondary: true, onClick: () => openEdit(row) }, { default: () => '编辑' }),
          h(NButton, { size: 'tiny', secondary: true, type: 'warning', onClick: () => openReset(row) }, { default: () => '修改密码' }),
          row.is_active
            ? h(NPopconfirm, { onPositiveClick: () => toggleActive(row, false) }, {
                trigger: () => h(NButton, { size: 'tiny', secondary: true, type: 'error' }, { default: () => '禁用' }),
                default: () => `确认禁用管理员「${row.username}」？禁用后其登录立即失效。`,
              })
            : h(NButton, { size: 'tiny', secondary: true, type: 'success', onClick: () => toggleActive(row, true) }, { default: () => '启用' }),
        ],
      })
    },
  },
]

async function loadAdmins() {
  loading.value = true
  try {
    const { data } = await http.get('/api/admin/admins')
    admins.value = data.admins || []
  } catch (e) {
    msg.error(e.response?.data?.detail || '加载管理员列表失败')
  } finally {
    loading.value = false
  }
}

async function createAdmin() {
  creating.value = true
  try {
    await http.post('/api/admin/admins', createForm.value)
    msg.success('管理员已创建')
    showCreate.value = false
    createForm.value = { username: '', display_name: '', password: '', role: 'admin' }
    await loadAdmins()
  } catch (e) {
    msg.error(e.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

function openEdit(row) {
  editTarget.value = row
  editForm.value = {
    username: row.username,
    display_name: row.display_name || '',
    role: row.role,
    is_active: row.is_active,
  }
  showEdit.value = true
}

async function saveEdit() {
  editing.value = true
  try {
    await http.put(`/api/admin/admins/${editTarget.value.id}`, editForm.value)
    msg.success('已保存')
    showEdit.value = false
    await loadAdmins()
  } catch (e) {
    msg.error(e.response?.data?.detail || '保存失败')
  } finally {
    editing.value = false
  }
}

async function toggleActive(row, next) {
  try {
    await http.put(`/api/admin/admins/${row.id}`, { is_active: next })
    msg.success(next ? '已启用' : '已禁用')
    await loadAdmins()
  } catch (e) {
    msg.error(e.response?.data?.detail || '操作失败')
  }
}

function openReset(row) {
  resetTarget.value = row
  resetForm.value = { new_password: '' }
  showReset.value = true
}

async function doReset() {
  resetting.value = true
  try {
    await http.put(`/api/admin/admins/${resetTarget.value.id}/password`, resetForm.value)
    msg.success('密码已重置')
    showReset.value = false
  } catch (e) {
    msg.error(e.response?.data?.detail || '重置失败')
  } finally {
    resetting.value = false
  }
}

onMounted(loadAdmins)
</script>
