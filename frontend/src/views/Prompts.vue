<template>
  <div>
    <div class="page-header">
      <h2 class="page-header-title">提示词库</h2>
      <div class="page-header-actions">
        <n-select v-model:value="filterCat" :options="catOptions" clearable placeholder="筛选分类" style="width:200px" />
        <n-button type="primary" @click="openCreate">+ 新增提示词</n-button>
      </div>
    </div>
    <n-data-table :columns="columns" :data="filtered" :pagination="{ pageSize: 20 }" :bordered="false" />

    <n-modal v-model:show="showModal" :title="editId ? '编辑提示词' : '新增提示词'" preset="card" style="width:560px">
      <n-form :model="form" label-placement="top">
        <n-form-item label="分类">
          <n-select v-model:value="form.category" :options="catOptions" />
        </n-form-item>
        <n-form-item label="标题">
          <n-input v-model:value="form.title" />
        </n-form-item>
        <n-form-item label="提示词内容">
          <n-input v-model:value="form.content" type="textarea" :rows="6" />
        </n-form-item>
        <n-form-item label="排序（数字越小越靠前）">
          <n-input-number v-model:value="form.sort_order" />
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
import { ref, computed, onMounted, h } from 'vue'
import { useMessage, NButton, NSpace, NTag } from 'naive-ui'
import http from '../api/http'

const msg = useMessage()
const prompts = ref([])
const filterCat = ref(null)
const showModal = ref(false)
const editId = ref(null)
const saving = ref(false)
const form = ref({ category: '', title: '', content: '', sort_order: 0 })

const CATEGORIES = ['抖音商品图','电商详情图','商品白底图','去除背景','图片修图','提取图片','分镜','商品标注','跨境电商图','跨境电商A+图']
const catOptions = CATEGORIES.map(c => ({ label: c, value: c }))

const filtered = computed(() =>
  filterCat.value ? prompts.value.filter(p => p.category === filterCat.value) : prompts.value
)

const columns = [
  { title: '分类', key: 'category', width: 120,
    render: row => h(NTag, { size: 'small', bordered: false }, { default: () => row.category }) },
  { title: '标题', key: 'title', width: 160 },
  { title: '内容', key: 'content', ellipsis: { tooltip: true } },
  { title: '排序', key: 'sort_order', width: 60 },
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
  const { data } = await http.get('/api/admin/prompts')
  prompts.value = data
}

function openCreate() {
  editId.value = null
  form.value = { category: CATEGORIES[0], title: '', content: '', sort_order: 0 }
  showModal.value = true
}

function openEdit(row) {
  editId.value = row.id
  form.value = { category: row.category, title: row.title, content: row.content, sort_order: row.sort_order }
  showModal.value = true
}

async function save() {
  saving.value = true
  try {
    if (editId.value) {
      await http.put(`/api/admin/prompts/${editId.value}`, form.value)
    } else {
      await http.post('/api/admin/prompts', form.value)
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
  await http.delete(`/api/admin/prompts/${id}`)
  msg.success('已删除')
  await load()
}

onMounted(load)
</script>