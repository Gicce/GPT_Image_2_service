<template>
  <div>
    <n-h2>模型管理</n-h2>
    <n-button type="primary" style="margin-bottom:16px" @click="openCreate">+ 新增模型</n-button>
    <n-data-table :columns="columns" :data="models" :pagination="{ pageSize: 20 }" />

    <n-modal v-model:show="showModal" :title="editId ? '编辑模型' : '新增模型'" preset="card" style="width:600px">
      <n-form :model="form" label-placement="top">
        <n-grid :cols="2" :x-gap="12">
          <n-gi>
            <n-form-item label="模型 ID（如 gpt-image-2）">
              <n-input v-model:value="form.name" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="显示名称">
              <n-input v-model:value="form.display_name" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="类型">
              <n-select v-model:value="form.model_type" :options="typeOptions" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="排序">
              <n-input-number v-model:value="form.sort_order" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="启用">
              <n-switch v-model:value="form.is_enabled" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="试用可用">
              <n-switch v-model:value="form.trial_allowed" />
            </n-form-item>
          </n-gi>
        </n-grid>
        <n-divider>计费参数（图片模型填每张价格，对话模型填每百万 token 价格）</n-divider>
        <n-grid :cols="2" :x-gap="12">
          <n-gi>
            <n-form-item label="图片单价 $（每张）">
              <n-input-number v-model:value="form.price_per_image" :precision="4" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="输入 Token 价格 $（每百万）">
              <n-input-number v-model:value="form.price_input_per_m" :precision="4" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="输出 Token 价格 $（每百万）">
              <n-input-number v-model:value="form.price_output_per_m" :precision="4" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="缓存 Token 价格 $（每百万）">
              <n-input-number v-model:value="form.price_cached_per_m" :precision="4" style="width:100%" />
            </n-form-item>
          </n-gi>
        </n-grid>
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
import { useMessage, NButton, NSpace, NTag, NSwitch } from 'naive-ui'
import http from '../api/http'

const msg = useMessage()
const models = ref([])
const showModal = ref(false)
const editId = ref(null)
const saving = ref(false)

const defaultForm = () => ({
  name: '', display_name: '', model_type: 'image', is_enabled: true,
  trial_allowed: false, sort_order: 0,
  price_per_image: 0.04, price_input_per_m: 0, price_output_per_m: 0, price_cached_per_m: 0,
})
const form = ref(defaultForm())
const typeOptions = [
  { label: '图片', value: 'image' },
  { label: '对话', value: 'chat' },
]

const columns = [
  { title: '模型 ID', key: 'name', width: 160 },
  { title: '显示名称', key: 'display_name', width: 140 },
  { title: '类型', key: 'model_type', width: 70,
    render: row => h(NTag, { type: row.model_type === 'image' ? 'info' : 'success', size: 'small' },
      { default: () => row.model_type === 'image' ? '图片' : '对话' }) },
  { title: '启用', key: 'is_enabled', width: 70,
    render: row => h(NTag, { type: row.is_enabled ? 'success' : 'default', size: 'small' },
      { default: () => row.is_enabled ? '是' : '否' }) },
  { title: '试用', key: 'trial_allowed', width: 70,
    render: row => h(NTag, { type: row.trial_allowed ? 'warning' : 'default', size: 'small' },
      { default: () => row.trial_allowed ? '是' : '否' }) },
  { title: '排序', key: 'sort_order', width: 60 },
  {
    title: '操作', key: 'actions', width: 120,
    render: row => h(NSpace, null, {
      default: () => [
        h(NButton, { size: 'small', onClick: () => openEdit(row) }, { default: () => '编辑' }),
        h(NButton, { size: 'small', type: 'error', onClick: () => del(row.id) }, { default: () => '删除' }),
      ]
    })
  }
]

async function load() {
  const { data } = await http.get('/api/admin/models')
  models.value = data
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
      await http.put(`/api/admin/models/${editId.value}`, form.value)
    } else {
      await http.post('/api/admin/models', form.value)
    }
    msg.success('保存成功')
    showModal.value = false
    await load()
  } catch {
    msg.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function del(id) {
  await http.delete(`/api/admin/models/${id}`)
  msg.success('已删除')
  await load()
}

onMounted(load)
</script>
