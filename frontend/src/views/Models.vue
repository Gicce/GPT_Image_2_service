<template>
  <div>
    <div class="page-header">
      <h2 class="page-header-title">模型管理</h2>
      <div class="page-header-actions">
        <n-button type="primary" @click="openCreate">+ 新增模型</n-button>
      </div>
    </div>
    <n-data-table :columns="columns" :data="models" :pagination="{ pageSize: 20 }" :bordered="false" />

    <n-modal v-model:show="showModal" :title="editId ? '编辑模型' : '新增模型'" preset="card" style="width:640px">
      <n-form :model="form" label-placement="top">
        <n-grid :cols="2" :x-gap="12">
          <n-gi>
            <n-form-item label="模型 ID（如 gpt-5.5）">
              <n-input v-model:value="form.name" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="显示名称">
              <n-input v-model:value="form.display_name" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="供应商">
              <n-input v-model:value="form.provider" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="分组">
              <n-select v-model:value="form.group" :options="groupOptions" tag filterable />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="类型">
              <n-select v-model:value="form.model_type" :options="typeOptions" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="计费方式">
              <n-select v-model:value="form.billing_type" :options="billingOptions" />
            </n-form-item>
          </n-gi>
          <n-gi v-if="editId">
            <n-form-item label="排序">
              <n-input-number v-model:value="form.sort_order" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="启用 / 试用可用">
              <n-space>
                <n-switch v-model:value="form.is_enabled" /><span>启用</span>
                <n-switch v-model:value="form.trial_allowed" /><span>试用</span>
              </n-space>
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="上下文窗口">
              <n-input-number v-model:value="form.context_window" :min="0" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="能力">
              <n-space>
                <n-switch v-model:value="form.supports_tools" /><span>工具</span>
                <n-switch v-model:value="form.supports_vision" /><span>视觉</span>
              </n-space>
            </n-form-item>
          </n-gi>
        </n-grid>
        <n-divider>计费参数</n-divider>
        <n-grid :cols="2" :x-gap="12" v-if="form.billing_type === 'per_call'">
          <n-gi :span="2">
            <n-form-item label="单次价格 $（每次调用）">
              <n-input v-model:value="form.price_per_call" placeholder="0.040" />
            </n-form-item>
          </n-gi>
        </n-grid>
        <n-grid :cols="3" :x-gap="12" v-if="form.billing_type === 'per_token'">
          <n-gi>
            <n-form-item label="输入 $/1K tokens">
              <n-input v-model:value="form.price_input" placeholder="0.0025" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="输出 $/1K tokens">
              <n-input v-model:value="form.price_output" placeholder="0.0150" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="缓存 $/1K tokens">
              <n-input v-model:value="form.price_cached" placeholder="0.0003" />
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
import { useMessage, NButton, NSpace, NTag } from 'naive-ui'
import http from '../api/http'

const msg = useMessage()
const models = ref([])
const showModal = ref(false)
const editId = ref(null)
const saving = ref(false)

const defaultForm = () => ({
  name: '', display_name: '', provider: 'OpenAI', billing_type: 'per_token',
  model_type: 'agent', group: '', is_enabled: true, trial_allowed: false,
  sort_order: 0, price_input: '', price_output: '', price_cached: '', price_per_call: '',
  context_window: 32768, supports_tools: false, supports_vision: false,
})
const form = ref(defaultForm())

const typeOptions = [
  { label: '图片', value: 'image' },
  { label: 'Agent', value: 'agent' },
  { label: '后处理', value: 'postprocess' },
]
const billingOptions = [
  { label: '按量计费（per token）', value: 'per_token' },
  { label: '按次计费（per call）', value: 'per_call' },
]
const groupOptions = ref([])

async function loadGroups() {
  const { data } = await http.get('/api/admin/groups')
  groupOptions.value = data.map(g => ({ label: g.name, value: g.name }))
}

const columns = [
  { title: '模型', key: 'name', width: 120 },
  { title: '显示名', key: 'display_name', width: 130 },
  { title: '分组', key: 'group', width: 100,
    render: row => h(NTag, { size: 'small', bordered: false }, { default: () => row.group }) },
  { title: '计费', key: 'billing_type', width: 70,
    render: row => row.billing_type === 'per_call' ? '按次' : '按量' },
  { title: '启用', key: 'is_enabled', width: 55,
    render: row => h(NTag, { type: row.is_enabled ? 'success' : 'default', size: 'small', bordered: false },
      { default: () => row.is_enabled ? '是' : '否' }) },
  { title: '排序', key: 'sort_order', width: 50 },
  {
    title: '操作', key: 'actions', width: 120,
    render: row => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'small', quaternary: true, onClick: () => openEdit(row) }, { default: () => '编辑' }),
        h(NButton, { size: 'small', quaternary: true, type: 'error', onClick: () => del(row.id) }, { default: () => '删除' }),
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

onMounted(() => { load(); loadGroups() })
</script>