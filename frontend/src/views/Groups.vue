<template>
  <div>
    <div class="page-header">
      <h2 class="page-header-title">分组管理</h2>
      <div class="page-header-actions">
        <n-button type="primary" @click="openCreate">添加分组</n-button>
      </div>
    </div>
    <n-data-table :columns="columns" :data="groups" :bordered="false" />
    <n-modal v-model:show="showModal" preset="card" :title="editId ? '编辑分组' : '添加分组'" style="width:420px">
      <n-form label-placement="left" label-width="70">
        <n-form-item label="名称">
          <n-input v-model:value="form.name" placeholder="如 codex、sora" />
        </n-form-item>
        <n-form-item label="描述">
          <n-input v-model:value="form.description" placeholder="可选描述" />
        </n-form-item>
        <n-form-item v-if="editId" label="排序">
          <n-input-number v-model:value="form.sort_order" :min="0" />
        </n-form-item>
      </n-form>
      <template #footer>
        <div style="display:flex;justify-content:flex-end;gap:8px">
          <n-button @click="showModal=false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="save">保存</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, onMounted, h } from 'vue'
import { useMessage, NButton, NSpace } from 'naive-ui'
import http from '../api/http'

const msg = useMessage()
const groups = ref([])
const showModal = ref(false)
const editId = ref(null)
const saving = ref(false)

const defaultForm = () => ({ name: '', description: '', sort_order: 0 })
const form = ref(defaultForm())

const columns = [
  { title: '名称', key: 'name', width: 140 },
  { title: '描述', key: 'description' },
  { title: '排序', key: 'sort_order', width: 70 },
  {
    title: '操作', key: 'actions', width: 140,
    render: row => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'small', quaternary: true, onClick: () => openEdit(row) }, { default: () => '编辑' }),
        h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => del(row.id) }, { default: () => '删除' }),
      ]
    })
  }
]

async function load() {
  const { data } = await http.get('/api/admin/groups')
  groups.value = data
}

function openCreate() {
  editId.value = null
  form.value = defaultForm()
  showModal.value = true
}

function openEdit(row) {
  editId.value = row.id
  form.value = { ...row }
  showModal.value = true
}

async function save() {
  saving.value = true
  try {
    if (editId.value) {
      await http.put(`/api/admin/groups/${editId.value}`, form.value)
    } else {
      await http.post('/api/admin/groups', form.value)
    }
    msg.success('保存成功')
    showModal.value = false
    await load()
  } catch (e) {
    msg.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function del(id) {
  try {
    await http.delete(`/api/admin/groups/${id}`)
    msg.success('已删除')
    await load()
  } catch (e) {
    msg.error(e.response?.data?.detail || '删除失败')
  }
}

onMounted(load)
</script>