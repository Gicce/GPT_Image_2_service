<template>
  <div class="skills-page">
    <div class="page-header skills-header">
      <div>
        <h2 class="page-header-title">Skill 内容中心</h2>
        <p>管理官方版本，并审核用户从视觉项目整理出的社区 Skill。</p>
      </div>
      <n-button v-if="activeTab === 'packages'" type="primary" @click="openCreate">创建新版本</n-button>
    </div>

    <n-tabs v-model:value="activeTab" type="segment" class="skills-tabs" @update:value="handleTabChange">
      <n-tab name="packages">公开版本</n-tab>
      <n-tab name="submissions">用户投稿</n-tab>
    </n-tabs>

    <n-card v-if="activeTab === 'packages'" :bordered="false" class="skills-card">
      <div class="filter-row">
        <n-select v-model:value="statusFilter" :options="statusOptions" clearable placeholder="全部状态" />
        <n-select v-model:value="domainFilter" :options="domainOptions" clearable placeholder="全部领域" />
        <n-button :loading="loading" @click="loadPackages">刷新</n-button>
      </div>

      <n-data-table
        :columns="columns"
        :data="packages"
        :loading="loading"
        :row-key="row => row.id"
        :scroll-x="1080"
      />
    </n-card>
    <n-card v-else :bordered="false" class="skills-card">
      <div class="filter-row">
        <n-select v-model:value="submissionStatus" :options="submissionStatusOptions" clearable placeholder="全部审核状态" />
        <n-select v-model:value="domainFilter" :options="domainOptions" clearable placeholder="全部领域" />
        <n-button :loading="submissionLoading" @click="loadSubmissions">刷新</n-button>
      </div>
      <n-data-table :columns="submissionColumns" :data="submissions" :loading="submissionLoading" :row-key="row => row.id" :scroll-x="1120" />
    </n-card>

    <n-modal v-model:show="showEditor" preset="card" class="skill-modal" :title="editorTitle" :mask-closable="false">
      <n-form label-placement="top">
        <div class="editor-grid">
          <n-form-item label="Skill ID">
            <n-input v-model:value="draft.skill_id" :disabled="!!editingId" placeholder="professional_desk_setup" />
          </n-form-item>
          <n-form-item label="版本">
            <n-input v-model:value="draft.version" :disabled="!!editingId" placeholder="1.1.0" />
          </n-form-item>
          <n-form-item label="名称">
            <n-input v-model:value="draft.name" placeholder="专业桌搭" />
          </n-form-item>
          <n-form-item label="领域">
            <n-select v-model:value="draft.domain" :options="domainOptions" />
          </n-form-item>
        </div>
        <n-form-item label="摘要">
          <n-input v-model:value="draft.summary" placeholder="向客户端展示的简短介绍" />
        </n-form-item>
        <n-form-item label="Skill Package JSON">
          <n-input v-model:value="payloadText" type="textarea" :rows="18" class="payload-editor" />
        </n-form-item>
        <n-alert v-if="editorError" type="error" :bordered="false">{{ editorError }}</n-alert>
      </n-form>
      <template #footer>
        <div class="modal-footer">
          <n-button @click="showEditor = false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="saveDraft">保存草稿</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="showPreview" preset="card" class="skill-modal" title="Skill 版本预览">
      <n-descriptions v-if="preview" :column="2" bordered>
        <n-descriptions-item label="名称">{{ preview.name }}</n-descriptions-item>
        <n-descriptions-item label="版本">{{ preview.version }}</n-descriptions-item>
        <n-descriptions-item label="领域">{{ domainLabel(preview.domain) }}</n-descriptions-item>
        <n-descriptions-item label="状态">{{ statusLabel(preview.status) }}</n-descriptions-item>
        <n-descriptions-item label="可用性">{{ availabilityLabel(preview.availability) }}</n-descriptions-item>
        <n-descriptions-item label="发布时间">{{ formatTime(preview.published_at) }}</n-descriptions-item>
      </n-descriptions>
      <pre v-if="preview" class="json-preview">{{ JSON.stringify(preview.payload, null, 2) }}</pre>
    </n-modal>

    <n-modal v-model:show="showSubmission" preset="card" class="skill-review-modal" title="社区 Skill 审核">
      <template v-if="submissionDetail">
        <n-descriptions :column="2" bordered>
          <n-descriptions-item label="名称">{{ submissionDetail.name }}</n-descriptions-item>
          <n-descriptions-item label="作者">{{ submissionDetail.author_display_name }}</n-descriptions-item>
          <n-descriptions-item label="领域">{{ domainLabel(submissionDetail.domain) }}</n-descriptions-item>
          <n-descriptions-item label="状态">{{ submissionStatusLabel(submissionDetail.status) }}</n-descriptions-item>
          <n-descriptions-item label="来源修订">R{{ submissionDetail.revision }}</n-descriptions-item>
          <n-descriptions-item label="授权样例">{{ submissionDetail.sample_count }} 张</n-descriptions-item>
        </n-descriptions>
        <div class="review-grid">
          <section><h3>来源事实（只读）</h3><pre class="json-preview">{{ JSON.stringify(submissionDetail.source_facts, null, 2) }}</pre></section>
          <section><h3>通用化结果与编译结构</h3><pre class="json-preview">{{ JSON.stringify(submissionDetail.payload, null, 2) }}</pre></section>
        </div>
        <section><h3>用户授权样例</h3><div class="review-samples"><div v-for="sample in submissionDetail.samples" :key="sample.id"><img v-if="sampleUrls[sample.id]" :src="sampleUrls[sample.id]" :alt="sample.file_name" /><div v-else class="sample-loading">加载中</div><span>{{ sample.file_name }}</span></div></div></section>
        <n-alert v-if="submissionDetail.review_message" type="warning" :bordered="false">{{ submissionDetail.review_message }}</n-alert>
        <n-form-item label="审核意见"><n-input v-model:value="reviewMessage" type="textarea" :rows="3" placeholder="退修或拒绝时必须说明具体原因" /></n-form-item>
      </template>
      <template #footer><div class="modal-footer"><n-button @click="showSubmission = false">关闭</n-button><n-button v-if="submissionDetail?.status === 'submitted'" @click="startReview">开始审核</n-button><template v-if="submissionDetail?.status === 'under_review'"><n-button type="warning" @click="requestChanges">要求修改</n-button><n-button type="error" @click="rejectSubmission">拒绝</n-button><n-button type="primary" @click="approveSubmission">批准并发布</n-button></template></div></template>
    </n-modal>
  </div>
</template>

<script setup>
import { computed, h, onMounted, reactive, ref } from 'vue'
import { NButton, NTag, useDialog, useMessage } from 'naive-ui'
import http from '../api/http'

const msg = useMessage()
const dialog = useDialog()
const loading = ref(false)
const saving = ref(false)
const packages = ref([])
const statusFilter = ref(null)
const domainFilter = ref(null)
const showEditor = ref(false)
const showPreview = ref(false)
const editingId = ref('')
const preview = ref(null)
const payloadText = ref('{}')
const editorError = ref('')
const draft = reactive({ skill_id: '', version: '', name: '', domain: 'desk_setup', summary: '' })
const activeTab = ref('packages')
const submissions = ref([])
const submissionStatus = ref(null)
const submissionLoading = ref(false)
const showSubmission = ref(false)
const submissionDetail = ref(null)
const reviewMessage = ref('')
const sampleUrls = ref({})

const statusOptions = [
  { label: '草稿', value: 'draft' },
  { label: '已发布', value: 'published' },
  { label: '已归档', value: 'archived' },
]
const submissionStatusOptions = [
  { label: '已提交', value: 'submitted' }, { label: '审核中', value: 'under_review' },
  { label: '需修改', value: 'changes_requested' }, { label: '已拒绝', value: 'rejected' },
  { label: '已批准', value: 'approved' }, { label: '已撤回', value: 'withdrawn' },
]
const domainOptions = [
  { label: '专业桌搭', value: 'desk_setup' },
  { label: '电商视觉', value: 'ecommerce' },
  { label: '产品视觉', value: 'product' },
  { label: '品牌广告', value: 'brand_ad' },
  { label: '建筑与室内', value: 'interior' },
  { label: '运动视觉', value: 'sports' },
  { label: 'UI 概念设计', value: 'ui' },
]

const editorTitle = computed(() => editingId.value ? '编辑 Skill 草稿' : '创建 Skill 新版本')
const domainLabel = value => domainOptions.find(item => item.value === value)?.label || value
const statusLabel = value => statusOptions.find(item => item.value === value)?.label || value
const submissionStatusLabel = value => submissionStatusOptions.find(item => item.value === value)?.label || value
const availabilityLabel = value => ({ ready: '正式可用', testing: '测试中', planned: '规划中' }[value] || value)
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN') : '—'

function statusTag(row) {
  const type = row.status === 'published' ? 'success' : row.status === 'draft' ? 'warning' : 'default'
  return h(NTag, { size: 'small', type, bordered: false }, { default: () => statusLabel(row.status) })
}

function actionButton(label, onClick, type = 'default') {
  return h(NButton, { size: 'small', type, tertiary: type === 'default', onClick }, { default: () => label })
}

const columns = [
  { title: 'Skill', key: 'name', minWidth: 150, render: row => h('div', [h('strong', row.name), h('div', { class: 'table-meta' }, row.skill_id)]) },
  { title: '领域', key: 'domain', width: 120, render: row => domainLabel(row.domain) },
  { title: '版本', key: 'version', width: 90 },
  { title: '状态', key: 'status', width: 90, render: statusTag },
  { title: '客户端可用性', key: 'availability', width: 110, render: row => availabilityLabel(row.availability) },
  { title: '更新时间', key: 'updated_at', width: 170, render: row => formatTime(row.updated_at) },
  {
    title: '操作', key: 'actions', width: 300, fixed: 'right',
    render: row => h('div', { class: 'row-actions' }, [
      actionButton('预览', () => { preview.value = row; showPreview.value = true }),
      ...(row.status === 'draft' ? [
        actionButton('编辑', () => openEdit(row)),
        actionButton('校验', () => validateRow(row)),
        actionButton('发布', () => confirmPublish(row), 'primary'),
      ] : []),
      ...(row.status === 'published' ? [actionButton('归档', () => confirmArchive(row))] : []),
      ...(row.status === 'archived' ? [actionButton('回滚到此版本', () => confirmRollback(row))] : []),
    ]),
  },
]

const submissionColumns = [
  { title: '投稿', key: 'name', minWidth: 180, render: row => h('div', [h('strong', row.name), h('div', { class: 'table-meta' }, `${row.author_display_name} · R${row.revision}`)]) },
  { title: '领域', key: 'domain', width: 120, render: row => domainLabel(row.domain) },
  { title: '版本', key: 'version', width: 90 },
  { title: '状态', key: 'status', width: 100, render: row => h(NTag, { size: 'small', type: row.status === 'approved' ? 'success' : row.status === 'rejected' ? 'error' : 'warning', bordered: false }, { default: () => submissionStatusLabel(row.status) }) },
  { title: '样例', key: 'sample_count', width: 80, render: row => `${row.sample_count} 张` },
  { title: '更新时间', key: 'updated_at', width: 170, render: row => formatTime(row.updated_at) },
  { title: '操作', key: 'actions', width: 120, fixed: 'right', render: row => actionButton('查看审核', () => openSubmission(row)) },
]

function handleTabChange(value) { if (value === 'submissions') loadSubmissions() }
/** 服务端错误统一结构化 {code, message}；兼容旧字符串 detail */
function errorText(error, fallback) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.errors?.length ? `${detail.message}（${detail.errors.join('；')}）` : detail.message
  if (Array.isArray(detail?.errors)) return detail.errors.join('；')
  return fallback
}
async function loadSubmissions() {
  submissionLoading.value = true
  try { const { data } = await http.get('/api/admin/skill-submissions', { params: { status: submissionStatus.value || undefined, domain: domainFilter.value || undefined } }); submissions.value = data.submissions || [] }
  catch (error) { msg.error(errorText(error, '加载用户投稿失败')) }
  finally { submissionLoading.value = false }
}
async function openSubmission(row) {
  const { data } = await http.get(`/api/admin/skill-submissions/${row.id}`)
  submissionDetail.value = data; reviewMessage.value = data.review_message || ''; showSubmission.value = true
  Object.values(sampleUrls.value).forEach(url => URL.revokeObjectURL(url)); sampleUrls.value = {}
  for (const sample of data.samples || []) {
    try { const response = await http.get(`/api/admin/skill-submissions/samples/${sample.id}`, { responseType: 'blob' }); sampleUrls.value = { ...sampleUrls.value, [sample.id]: URL.createObjectURL(response.data) } } catch { /* 单个样例失败不阻断审核 */ }
  }
}
async function reviewAction(path, body) {
  try { const { data } = await http.post(`/api/admin/skill-submissions/${submissionDetail.value.id}/${path}`, body); submissionDetail.value = data.submission || data; msg.success(path === 'approve' ? '社区 Skill 已发布' : '审核状态已更新'); await loadSubmissions() }
  catch (error) { msg.error(errorText(error, '审核操作失败')) }
}
const startReview = () => reviewAction('start-review')
const requestChanges = () => reviewAction('request-changes', { message: reviewMessage.value })
const rejectSubmission = () => reviewAction('reject', { message: reviewMessage.value })
const approveSubmission = () => reviewAction('approve')

async function loadPackages() {
  loading.value = true
  try {
    const { data } = await http.get('/api/admin/skill-packages', { params: {
      status: statusFilter.value || undefined,
      domain: domainFilter.value || undefined,
    } })
    packages.value = data.packages || []
  } catch (error) {
    msg.error(errorText(error, '加载 Skill 目录失败'))
  } finally {
    loading.value = false
  }
}

function blankPayload() {
  return {
    availability: 'testing', wizard_steps: [{ id: 'brief', name: '创作需求' }],
    profiles: [], asset_roles: [], core_rules: [], review_rubric: ['任务完成度', '技术质量'],
  }
}

function openCreate() {
  editingId.value = ''
  Object.assign(draft, { skill_id: '', version: '', name: '', domain: 'desk_setup', summary: '' })
  payloadText.value = JSON.stringify(blankPayload(), null, 2)
  editorError.value = ''
  showEditor.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(draft, { skill_id: row.skill_id, version: row.version, name: row.name, domain: row.domain, summary: row.summary })
  payloadText.value = JSON.stringify(row.payload || {}, null, 2)
  editorError.value = ''
  showEditor.value = true
}

async function saveDraft() {
  editorError.value = ''
  let payload
  try { payload = JSON.parse(payloadText.value) } catch { editorError.value = 'JSON 格式不正确，请检查后重试。'; return }
  saving.value = true
  try {
    if (editingId.value) {
      await http.put(`/api/admin/skill-packages/${editingId.value}`, { name: draft.name, domain: draft.domain, summary: draft.summary, payload })
    } else {
      await http.post('/api/admin/skill-packages', { ...draft, payload })
    }
    msg.success('Skill 草稿已保存')
    showEditor.value = false
    await loadPackages()
  } catch (error) {
    editorError.value = errorText(error, '保存失败')
  } finally {
    saving.value = false
  }
}

async function validateRow(row) {
  const { data } = await http.post(`/api/admin/skill-packages/${row.id}/validate`)
  data.ok ? msg.success('结构校验通过') : msg.error(data.errors.join('；'))
}

function confirmAction(title, content, positiveText, action) {
  dialog.warning({ title, content, positiveText, negativeText: '取消', onPositiveClick: action })
}
function confirmPublish(row) { confirmAction('发布 Skill 版本', `发布 ${row.name} ${row.version}，当前已发布版本将归档。`, '发布', async () => { await http.post(`/api/admin/skill-packages/${row.id}/publish`); msg.success('Skill 版本已发布'); await loadPackages() }) }
function confirmArchive(row) { confirmAction('归档 Skill 版本', `归档后客户端目录将不再提供 ${row.name} ${row.version}。`, '归档', async () => { await http.post(`/api/admin/skill-packages/${row.id}/archive`); msg.success('Skill 版本已归档'); await loadPackages() }) }
function confirmRollback(row) { confirmAction('回滚 Skill 版本', `将 ${row.name} 恢复到 ${row.version}，当前版本会自动归档。`, '确认回滚', async () => { await http.post(`/api/admin/skill-packages/${row.id}/rollback`); msg.success('Skill 版本已回滚'); await loadPackages() }) }

onMounted(loadPackages)
</script>

<style scoped>
.skills-page { min-width: 0; }
.skills-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.skills-header p { margin: 6px 0 0; color: var(--cy-text-muted); }
.skills-card { background: var(--cy-bg-elevated) !important; border: 1px solid var(--cy-border) !important; border-radius: 10px !important; }
.skills-tabs { width: 260px; margin-bottom: 16px; }
.filter-row { display: grid; grid-template-columns: 180px 200px auto; gap: 12px; margin-bottom: 16px; }
.table-meta { color: var(--cy-text-dim); font-size: 12px; margin-top: 4px; }
.row-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.editor-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 12px; }
.payload-editor :deep(textarea), .json-preview { font-family: Consolas, monospace; font-size: 12px; }
.json-preview { max-height: 50vh; overflow: auto; padding: 16px; margin-top: 16px; background: var(--cy-bg-muted); border: 1px solid var(--cy-border); border-radius: 8px; white-space: pre-wrap; }
:global(.skill-modal) { width: min(920px, calc(100vw - 48px)); max-height: calc(100vh - 48px); overflow: auto; }
.review-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}.review-samples{display:flex;gap:12px;overflow:auto}.review-samples div{display:grid;gap:6px;min-width:140px}.review-samples img{width:140px;height:105px;object-fit:cover;border-radius:8px;border:1px solid var(--cy-border)}:global(.skill-review-modal){width:min(1100px,calc(100vw - 48px));max-height:calc(100vh - 48px);overflow:auto}
.sample-loading{display:grid!important;place-items:center;width:140px;height:105px;border-radius:8px;background:var(--cy-bg-muted);color:var(--cy-text-muted)}
@media (max-width: 1000px) { .editor-grid { grid-template-columns: 1fr; } .filter-row { grid-template-columns: 1fr 1fr auto; } }
</style>
