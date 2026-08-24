<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">定价规则</h2>
        <p class="page-header-subtitle">CY 点数定价唯一来源 · Price Guard 目标毛利校验</p>
      </div>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#00d4aa,#00d4aa00)"></div>
        <div class="stat-card-label">当前单张（点）</div>
        <div class="stat-card-value">{{ activeRule ? activeRule.unit_credits : '-' }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#f59e0b,#f59e0b00)"></div>
        <div class="stat-card-label">最低建议（点）</div>
        <div class="stat-card-value">{{ activePreview ? activePreview.min_unit_credits : '-' }}</div>
      </div>
      <div class="stat-card" :class="{ 'stat-danger': activePreview && activePreview.below_target }">
        <div class="stat-card-accent" :style="activePreview && activePreview.below_target
          ? 'background:linear-gradient(90deg,#ef4444,#ef444400)'
          : 'background:linear-gradient(90deg,#0f766e,#0f766e00)'"></div>
        <div class="stat-card-label">预计毛利率（安全成本口径）</div>
        <div class="stat-card-value">
          {{ activePreview && activePreview.gross_margin != null
            ? (parseFloat(activePreview.gross_margin) * 100).toFixed(1) + '%' : '-' }}
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#6366f1,#6366f100)"></div>
        <div class="stat-card-label">兑换率</div>
        <div class="stat-card-value">¥1 = {{ creditsPerCny }} 点</div>
      </div>
    </div>

    <div class="table-card">
      <div class="table-card-header">
        <span class="table-card-title">规则列表</span>
        <n-button size="small" @click="openEdit(activeRule)" :disabled="!activeRule">编辑定价</n-button>
      </div>
      <n-data-table :columns="ruleColumns" :data="rules" :loading="loading" :bordered="false"
        :pagination="false" :row-key="row => row.id" />
    </div>

    <div class="table-card" style="margin-top:24px">
      <div class="table-card-header">
        <span class="table-card-title">业务配置</span>
        <n-button size="small" @click="loadConfig" :loading="configLoading">刷新</n-button>
      </div>
      <n-data-table :columns="configColumns" :data="configs" :loading="configLoading" :bordered="false"
        :pagination="false" :row-key="row => row.key" />
    </div>

    <div v-if="isSuperAdmin" class="table-card" style="margin-top:24px">
      <div class="table-card-header">
        <span class="table-card-title">旧美元余额迁移（高风险）</span>
      </div>
      <p style="font-size:13px;color:var(--cy-text-muted);margin:0 0 12px">
        生产环境部署后：先「预演核对」报告（用户数 / 旧总余额 / 转换后总点数 / 异常数），确认无异常再执行迁移。迁移幂等。
      </p>
      <div style="display:flex;gap:12px">
        <n-button size="small" @click="runMigration('preview')" :loading="migrationLoading">预演核对</n-button>
        <n-button size="small" type="error" @click="runMigration('apply')" :loading="migrationLoading">执行迁移</n-button>
      </div>
      <pre v-if="migrationReport" class="migration-report">{{ migrationReport }}</pre>
    </div>

    <!-- 编辑弹窗 -->
    <n-modal v-model:show="editVisible" preset="card" title="编辑定价规则" style="width:560px">
      <n-form label-placement="left" label-width="150">
        <n-form-item label="单张售价（CY 点）">
          <n-input-number v-model:value="form.unit_credits" :min="1" :max="100000" style="width:100%" />
        </n-form-item>
        <n-form-item label="采购成本（¥/张）">
          <n-input-number v-model:value="form.nominal_unit_cost_rmb" :min="0" :step="0.01" style="width:100%" />
        </n-form-item>
        <n-form-item label="目标毛利率">
          <n-input-number v-model:value="form.target_margin" :min="0.01" :max="0.99" :step="0.05" style="width:100%" />
        </n-form-item>
        <n-form-item label="成本安全垫">
          <n-input-number v-model:value="form.safety_buffer" :min="0" :max="0.99" :step="0.05" style="width:100%" />
        </n-form-item>
        <n-form-item label="最低价取整步长">
          <n-input-number v-model:value="form.rounding_step" :min="1" :max="1000" style="width:100%" />
        </n-form-item>
        <n-form-item label="上游路由">
          <n-input v-model:value="form.provider_route" />
        </n-form-item>
        <n-form-item label="启用">
          <n-switch v-model:value="form.enabled" />
        </n-form-item>
      </n-form>

      <!-- 实时毛利测算（与服务端同一公式） -->
      <div class="margin-preview" :class="{ 'margin-preview-danger': preview && preview.below_target }">
        <template v-if="preview">
          <div class="mp-row"><span>销售收入</span><b>¥{{ fmt(preview.revenue_rmb) }}</b></div>
          <div class="mp-row"><span>安全成本（成本×{{ (1 + parseFloat(preview.safety_buffer)).toFixed(2) }}）</span><b>¥{{ fmt(preview.effective_unit_cost_rmb) }}</b></div>
          <div class="mp-row"><span>预计毛利润</span><b>¥{{ fmt(preview.gross_profit_rmb) }}</b></div>
          <div class="mp-row"><span>预计毛利率</span><b>{{ pct(preview.gross_margin) }}</b></div>
          <div class="mp-row"><span>最低建议售价</span><b>{{ preview.min_unit_credits }} 点</b></div>
          <div v-if="preview.below_target" class="mp-warn">低于目标毛利（{{ pct(preview.target_margin) }}）——普通管理员无法保存；超级管理员可强制保存（需填原因）</div>
        </template>
      </div>

      <template v-if="preview && preview.below_target">
        <n-form label-placement="left" label-width="150" style="margin-top:12px">
          <n-form-item label="强制保存">
            <n-switch v-model:value="form.force" />
          </n-form-item>
          <n-form-item v-if="form.force" label="强制原因（必填）">
            <n-input v-model:value="form.override_reason" type="textarea" :rows="2" maxlength="255" />
          </n-form-item>
        </n-form>
      </template>

      <template #footer>
        <div style="display:flex;justify-content:flex-end;gap:12px">
          <n-button @click="editVisible = false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="save">保存</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { NTag, useMessage } from 'naive-ui'
import http from '../api/http'

const message = useMessage()
const loading = ref(false)
const rules = ref([])
const creditsPerCny = ref(100)
const configs = ref([])
const configLoading = ref(false)
const isSuperAdmin = ref(false)
const migrationLoading = ref(false)
const migrationReport = ref('')

const activeRule = computed(() => rules.value.find(r => r.enabled) || rules.value[0] || null)
const activePreview = computed(() => activeRule.value ? activeRule.value.margin_preview : null)

// 与服务端 margin_math 同一套公式的本地实时预览
const preview = computed(() => {
  if (!form.unit_credits) return null
  const cpc = creditsPerCny.value || 100
  const revenue = form.unit_credits / cpc
  const effectiveCost = (form.nominal_unit_cost_rmb || 0) * (1 + (form.safety_buffer || 0))
  const profit = revenue - effectiveCost
  const margin = revenue > 0 ? profit / revenue : null
  const target = form.target_margin || 0.7
  let minUnit = 0
  if (target < 1) {
    const raw = effectiveCost / (1 - target) * cpc
    const step = Math.max(1, form.rounding_step || 10)
    minUnit = Math.ceil(raw / step) * step
  }
  return {
    revenue_rmb: revenue.toFixed(6),
    effective_unit_cost_rmb: effectiveCost.toFixed(6),
    gross_profit_rmb: profit.toFixed(6),
    gross_margin: margin == null ? null : margin.toFixed(4),
    target_margin: String(target),
    safety_buffer: String(form.safety_buffer || 0),
    min_unit_credits: minUnit,
    below_target: margin == null || margin < target,
  }
})

const ruleColumns = [
  { title: '功能', key: 'feature', width: 80 },
  { title: '模型', key: 'model', width: 130 },
  { title: '单张（点）', key: 'unit_credits', width: 100 },
  { title: '成本（¥/张）', key: 'nominal_unit_cost_rmb', width: 110, render: r => '¥' + r.nominal_unit_cost_rmb },
  { title: '目标毛利', key: 'target_margin', width: 90, render: r => pct(r.target_margin) },
  { title: '安全垫', key: 'safety_buffer', width: 80, render: r => pct(r.safety_buffer) },
  {
    title: '预计毛利率', key: 'margin', width: 110,
    render: r => {
      if (!r.margin_preview) return '-'
      const m = r.margin_preview.gross_margin
      if (m == null) return '-'
      const danger = r.margin_preview.below_target
      return h(NTag, { type: danger ? 'error' : 'success', size: 'small', bordered: false },
        { default: () => pct(m) })
    }
  },
  {
    title: '最低建议（点）', key: 'min', width: 120,
    render: r => r.margin_preview ? r.margin_preview.min_unit_credits : '-'
  },
  { title: '版本', key: 'version', width: 70 },
  {
    title: '强制覆盖', key: 'override', width: 110,
    render: r => r.override_at
      ? h(NTooltipCompat, { content: `${r.override_by || ''} ${r.override_at}：${r.override_reason || ''}` },
          { default: () => h(NTag, { type: 'warning', size: 'small', bordered: false }, { default: () => '强制' }) })
      : '-'
  },
  {
    title: '状态', key: 'enabled', width: 80,
    render: r => h(NTag, { type: r.enabled ? 'success' : 'default', size: 'small', bordered: false },
      { default: () => r.enabled ? '生效中' : '停用' })
  },
]

// NTooltip 简化包装（避免列定义里过长）
const NTooltipCompat = {
  props: ['content'],
  template: `<n-tooltip trigger="hover" style="max-width:320px"><slot /><template #trigger><slot /></template></n-tooltip>`,
}

const configColumns = [
  { title: '配置键', key: 'key', width: 200 },
  { title: '值', key: 'value', width: 140 },
  { title: '默认值', key: 'default', width: 100 },
  { title: '说明', key: 'description', width: 260 },
  {
    title: '操作', key: 'actions', width: 80,
    render: row => h('a', {
      style: 'cursor:pointer;color:#0f766e;font-size:13px',
      onClick: () => editConfig(row),
    }, '修改')
  },
]

const editVisible = ref(false)
const saving = ref(false)
const editingRuleId = ref(null)
const form = ref({
  unit_credits: 50, nominal_unit_cost_rmb: 0.2, target_margin: 0.7,
  safety_buffer: 0.1, rounding_step: 10, provider_route: 'packyapi',
  enabled: true, force: false, override_reason: '',
})

async function loadRules() {
  loading.value = true
  try {
    const { data } = await http.get('/api/admin/pricing/rules')
    rules.value = data.rules || []
    creditsPerCny.value = data.credits_per_cny || 100
  } catch (e) {
    message.error('加载定价规则失败')
  } finally {
    loading.value = false
  }
}

async function loadConfig() {
  configLoading.value = true
  try {
    const { data } = await http.get('/api/admin/system-config')
    configs.value = data.configs || []
  } catch (e) {
    message.error('加载业务配置失败')
  } finally {
    configLoading.value = false
  }
}

async function loadRole() {
  try {
    const { data } = await http.get('/api/admin/admins/me')
    isSuperAdmin.value = data.role === 'super_admin'
  } catch (e) { /* ignore */ }
}

function openEdit(rule) {
  if (!rule) return
  editingRuleId.value = rule.id
  form.value = {
    unit_credits: rule.unit_credits,
    nominal_unit_cost_rmb: parseFloat(rule.nominal_unit_cost_rmb),
    target_margin: parseFloat(rule.target_margin),
    safety_buffer: parseFloat(rule.safety_buffer),
    rounding_step: rule.rounding_step,
    provider_route: rule.provider_route,
    enabled: rule.enabled,
    force: false,
    override_reason: '',
  }
  editVisible.value = true
}

async function save() {
  saving.value = true
  try {
    const payload = {
      unit_credits: form.value.unit_credits,
      nominal_unit_cost_rmb: String(form.value.nominal_unit_cost_rmb),
      target_margin: String(form.value.target_margin),
      safety_buffer: String(form.value.safety_buffer),
      rounding_step: form.value.rounding_step,
      provider_route: form.value.provider_route,
      enabled: form.value.enabled,
    }
    if (form.value.force) {
      payload.force = true
      payload.override_reason = form.value.override_reason
    }
    const { data } = await http.put(`/api/admin/pricing/rules/${editingRuleId.value}`, payload)
    if (data.rule) {
      message.success(`定价已更新（版本 v${data.rule.version}）`)
    }
    editVisible.value = false
    await loadRules()
  } catch (e) {
    const detail = e.response?.data?.detail
    if (detail && detail.code === 'BELOW_TARGET_MARGIN') {
      message.error(detail.message || '低于目标毛利，禁止保存')
    } else {
      message.error(detail?.message || detail || '保存失败')
    }
  } finally {
    saving.value = false
  }
}

function editConfig(row) {
  // eslint-disable-next-line no-alert
  const value = window.prompt(`修改 ${row.key}（${row.description || ''}）`, row.value)
  if (value === null || value === row.value) return
  http.put('/api/admin/system-config', { key: row.key, value: String(value).trim() })
    .then(() => { message.success('配置已更新'); loadConfig() })
    .catch(err => {
      message.error(err.response?.data?.detail || '配置更新失败')
    })
}

async function runMigration(action) {
  if (action === 'apply') {
    // eslint-disable-next-line no-alert
    const ok = window.confirm('确认执行旧美元余额 → CY 点数迁移？请先完成「预演核对」并无异常。')
    if (!ok) return
  }
  migrationLoading.value = true
  try {
    const { data } = await http.post('/api/admin/billing/credits-migration', { action })
    migrationReport.value = JSON.stringify(data, null, 2)
    if (action === 'apply') message.success('迁移执行完成')
  } catch (e) {
    const detail = e.response?.data?.detail
    migrationReport.value = JSON.stringify(detail || e.response?.data || e.message, null, 2)
    message.error(detail?.message || '迁移请求失败')
  } finally {
    migrationLoading.value = false
  }
}

function fmt(v) { return parseFloat(v).toFixed(4) }
function pct(v) { return v == null ? '-' : (parseFloat(v) * 100).toFixed(1) + '%' }

onMounted(() => {
  loadRules()
  loadConfig()
  loadRole()
})
</script>

<style scoped>
.stats-row { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
.stat-card { position: relative; background: #fff; border-radius: var(--cy-radius); border: 1px solid var(--cy-border); padding: 20px 24px; min-width: 180px; overflow: hidden; }
.stat-card-accent { position: absolute; top: 0; left: 0; right: 0; height: 3px; }
.stat-card-label { font-size: 13px; color: var(--cy-text-muted); margin-bottom: 4px; }
.stat-card-value { font-size: 28px; font-weight: 700; color: var(--cy-text); font-family: var(--cy-font-mono); }
.stat-danger .stat-card-value { color: #ef4444; }

.table-card { background: #fff; border: 1px solid var(--cy-border); border-radius: var(--cy-radius); padding: 16px 20px; }
.table-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.table-card-title { font-weight: 600; }

.margin-preview { border: 1px solid var(--cy-border); border-radius: var(--cy-radius); padding: 12px 16px; background: #fafafa; }
.margin-preview-danger { border-color: #fecaca; background: #fef2f2; }
.mp-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; color: var(--cy-text-muted); }
.mp-row b { color: var(--cy-text); font-family: var(--cy-font-mono); }
.mp-warn { margin-top: 8px; color: #dc2626; font-size: 13px; font-weight: 500; }

.migration-report { margin-top: 12px; background: #0f172a; color: #a7f3d0; padding: 12px; border-radius: 8px; font-size: 12px; max-height: 320px; overflow: auto; }
</style>
