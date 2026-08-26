<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">系统设置</h2>
        <p class="page-header-subtitle">集中管理业务参数、基础设施、支付邮件、安全与运维操作</p>
      </div>
      <div class="page-header-actions">
        <n-button size="small" :loading="loading || businessLoading" @click="refreshAll">刷新</n-button>
        <n-button size="small" @click="checkEnvironment">环境检查</n-button>
      </div>
    </div>

    <div class="status-overview">
      <div v-for="item in statusItems" :key="item.label" class="status-card">
        <div class="status-dot" :class="item.type"></div>
        <div class="status-card-content">
          <div class="status-card-label">{{ item.label }}</div>
          <div class="status-card-value">{{ item.value }}</div>
        </div>
      </div>
    </div>

    <n-tabs v-model:value="activeTab" type="line" animated>
      <n-tab-pane name="business" tab="业务参数">
        <div class="business-grid">
          <n-card v-for="group in businessGroups" :key="group.key" :title="group.title" class="settings-card">
            <p class="group-description">{{ group.description }}</p>
            <n-form label-placement="top" :show-feedback="false">
              <n-form-item v-for="item in group.items" :key="item.key" :label="item.description">
                <n-switch v-if="item.key === 'trial_feature_enabled'" v-model:value="businessValues[item.key]" />
                <n-input-number v-else v-model:value="businessValues[item.key]" :precision="item.key.includes('margin') || item.key.includes('buffer') ? 2 : 0" style="width:100%" />
              </n-form-item>
            </n-form>
            <template #footer>
              <div class="card-footer">
                <n-button type="primary" size="small" :loading="businessSaving[group.key]" @click="saveBusinessGroup(group)">保存本组</n-button>
              </div>
            </template>
          </n-card>
        </div>
      </n-tab-pane>

      <n-tab-pane name="infrastructure" tab="基础设施">
        <n-alert type="info" :bordered="false" class="section-alert">
          管理员账号与登录记录已移至“管理员与登录”。敏感字段留空表示不修改。
        </n-alert>
        <div class="config-grid">
          <n-card v-for="cat in categories" :key="cat.icon" class="settings-card">
            <template #header>
              <div>
                <div class="card-title">{{ categoryTitles[cat.icon] || cat.label }}</div>
                <div class="group-description">{{ categoryDescriptions[cat.icon] || '' }}</div>
              </div>
            </template>
            <n-form label-placement="top" :show-feedback="false">
              <n-form-item v-for="item in cat.items" :key="item.key" :label="item.description">
                <n-input v-if="item.field_type === 'password'" v-model:value="formValues[item.key]" type="password" show-password-on="click" :placeholder="item.is_sensitive ? '不修改请留空' : '请输入'" />
                <n-input-number v-else-if="item.field_type === 'number'" v-model:value="formValues[item.key]" style="width:100%" />
                <n-switch v-else-if="item.field_type === 'boolean'" v-model:value="formValues[item.key]" />
                <n-input v-else v-model:value="formValues[item.key]" />
              </n-form-item>
            </n-form>
            <template #footer>
              <div class="card-footer">
                <n-button type="primary" size="small" :loading="saving[cat.icon]" @click="saveCategory(cat)">保存配置</n-button>
              </div>
            </template>
          </n-card>
        </div>
      </n-tab-pane>

      <n-tab-pane name="operations" tab="运维操作">
        <n-card class="operation-card" title="后端服务维护">
          <n-alert type="warning" :bordered="false" class="section-alert">
            重启会造成约 5–10 秒服务中断，请避开支付回调和配置保存操作。
          </n-alert>
          <div class="operation-actions">
            <n-button type="warning" :loading="restarting" @click="showRestartDialog">重启后端服务</n-button>
            <n-tag v-if="restartStatus" :type="restartStatus === 'healthy' ? 'success' : restartStatus === 'failed' ? 'error' : 'warning'">
              {{ restartMessages[restartStatus] }}
            </n-tag>
          </div>
        </n-card>
      </n-tab-pane>
    </n-tabs>

    <n-modal v-model:show="restartModalVisible" preset="dialog" title="确认重启后端服务">
      <n-alert type="warning" :bordered="false" class="section-alert">该操作会短暂中断服务。</n-alert>
      <p class="confirm-label">请输入 <code>RESTART</code> 确认：</p>
      <n-input v-model:value="restartConfirmText" placeholder="RESTART" />
      <template #action>
        <n-button @click="restartModalVisible = false">取消</n-button>
        <n-button type="warning" :disabled="restartConfirmText !== 'RESTART'" :loading="restarting" @click="doRestart">确认重启</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useMessage } from 'naive-ui'
import http from '../api/http'

const msg = useMessage()
const activeTab = ref('business')
const loading = ref(false)
const businessLoading = ref(false)
const categories = ref([])
const businessConfigs = ref([])
const formValues = reactive({})
const businessValues = reactive({})
const saving = reactive({})
const businessSaving = reactive({})
const restarting = ref(false)
const restartStatus = ref(null)
const restartModalVisible = ref(false)
const restartConfirmText = ref('')
const securitySummary = ref({ admin_count: '-', version: '-' })

const categoryTitles = { database: '基础设施', security: '认证与安全', wechat: '支付配置', smtp: '邮件服务', server: 'AI Runtime' }
const categoryDescriptions = {
  database: '数据库、缓存与服务连接参数', security: 'JWT 密钥与服务认证参数', wechat: '微信支付商户配置',
  smtp: 'SMTP 发信配置', server: 'AI 上游服务与 Runtime Token 配置',
}
const businessGroupMeta = [
  { key: 'credits', title: '点数与兑换', description: 'CY 点数兑换及历史余额迁移口径', keys: ['credits_per_cny', 'legacy_usd_to_credits'] },
  { key: 'trial', title: '试用策略', description: '新用户试用开关、赠送点数、有效天数与活动版本', keys: ['trial_feature_enabled', 'trial_grant_credits', 'trial_valid_days', 'trial_campaign_version'] },
  { key: 'margin', title: '成本与毛利', description: '定价保护线和采购成本安全垫', keys: ['target_margin', 'cost_safety_buffer'] },
  { key: 'recharge', title: '充值范围', description: '单笔人民币充值上下限', keys: ['recharge_min_cny', 'recharge_max_cny'] },
]

const businessGroups = computed(() => businessGroupMeta.map(group => ({
  ...group,
  items: group.keys.map(key => businessConfigs.value.find(item => item.key === key)).filter(Boolean),
})))

const isHttps = computed(() => window.location.protocol === 'https:')
const wechatConfigured = computed(() => Boolean(formValues.WECHAT_MCHID && formValues.WECHAT_APPID && formValues.WECHAT_APIV3_KEY))
const runtimeConfigured = computed(() => Boolean(formValues.PACKYAPI_IMAGE_MASTER_TOKEN))
const statusItems = computed(() => [
  { label: '当前环境', value: import.meta.env.MODE === 'production' ? '生产环境' : '开发环境', type: import.meta.env.MODE === 'production' ? 'success' : 'warning' },
  { label: '管理员与安全', value: `${securitySummary.value.admin_count} 个账号 · ${isHttps.value ? 'HTTPS' : 'HTTP'}`, type: isHttps.value ? 'success' : 'warning' },
  { label: '微信支付', value: wechatConfigured.value ? '已配置' : '未配置', type: wechatConfigured.value ? 'success' : 'warning' },
  { label: 'AI Runtime', value: runtimeConfigured.value ? '已配置' : '未配置', type: runtimeConfigured.value ? 'success' : 'warning' },
  { label: '服务版本', value: securitySummary.value.version || '-', type: 'success' },
])
const restartMessages = { restarting: '服务正在重启…', healthy: '服务已恢复', failed: '服务恢复超时' }

onMounted(refreshAll)

async function refreshAll() {
  await Promise.all([loadConfig(), loadBusinessConfig(), loadSecuritySummary()])
}

async function loadConfig() {
  loading.value = true
  try {
    const { data } = await http.get('/api/admin/config')
    categories.value = data.categories || []
    for (const cat of categories.value) {
      saving[cat.icon] = false
      for (const item of cat.items) {
        formValues[item.key] = item.field_type === 'boolean'
          ? ['true', 'True', '1'].includes(item.value)
          : item.field_type === 'number' ? Number(item.value || 0) : item.value
      }
    }
  } catch { msg.error('加载基础设施配置失败') } finally { loading.value = false }
}

async function loadBusinessConfig() {
  businessLoading.value = true
  try {
    const { data } = await http.get('/api/admin/system-config')
    businessConfigs.value = data.configs || []
    for (const item of businessConfigs.value) {
      businessValues[item.key] = item.key === 'trial_feature_enabled' ? item.value === 'true' : Number(item.value)
    }
  } catch { msg.error('加载业务参数失败') } finally { businessLoading.value = false }
}

async function loadSecuritySummary() {
  try {
    const health = await http.get('/api/health').catch(() => ({ data: {} }))
    let adminCount = '-'
    try { adminCount = (await http.get('/api/admin/admins')).data.total ?? '-' } catch {}
    securitySummary.value = { admin_count: adminCount, version: health.data.version || '-' }
  } catch {}
}

async function saveBusinessGroup(group) {
  businessSaving[group.key] = true
  try {
    for (const item of group.items) {
      const value = item.key === 'trial_feature_enabled' ? String(Boolean(businessValues[item.key])) : String(businessValues[item.key])
      await http.put('/api/admin/system-config', { key: item.key, value, reason: `系统设置：${group.title}` })
    }
    msg.success(`${group.title}已保存`)
    await loadBusinessConfig()
  } catch (error) { msg.error(error.response?.data?.detail || '业务参数保存失败') } finally { businessSaving[group.key] = false }
}

async function saveCategory(cat) {
  saving[cat.icon] = true
  const updates = {}
  for (const item of cat.items) {
    let value = formValues[item.key]
    if (item.field_type === 'boolean') value = value ? 'true' : 'false'
    if (item.field_type === 'number') value = String(value)
    if (item.is_sensitive && !value) continue
    updates[item.key] = value
  }
  try { await http.put('/api/admin/config', { updates }); msg.success('配置已保存') }
  catch { msg.error('配置保存失败') } finally { saving[cat.icon] = false }
}

function checkEnvironment() {
  const issues = []
  if (!wechatConfigured.value) issues.push('微信支付未完整配置')
  if (!runtimeConfigured.value) issues.push('AI Runtime Token 未配置')
  issues.length ? msg.warning(issues.join('；')) : msg.success('关键环境配置检查通过')
}

function showRestartDialog() { restartConfirmText.value = ''; restartModalVisible.value = true }

async function doRestart() {
  if (restartConfirmText.value !== 'RESTART') return
  restartModalVisible.value = false
  restarting.value = true
  restartStatus.value = 'restarting'
  try { await http.post('/api/admin/config/restart') } catch {}
  for (let i = 0; i < 15; i += 1) {
    await new Promise(resolve => setTimeout(resolve, 2000))
    try { await http.get('/api/health'); restartStatus.value = 'healthy'; msg.success('服务已恢复'); break }
    catch { if (i === 14) { restartStatus.value = 'failed'; msg.error('服务恢复超时') } }
  }
  restarting.value = false
}
</script>

<style scoped>
.status-overview { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; margin-bottom:20px; }
.status-card { display:flex; align-items:center; gap:12px; min-width:0; padding:14px 16px; background:var(--cy-bg-elevated); border:1px solid var(--cy-border); border-radius:var(--cy-radius-lg); }
.status-dot { width:10px; height:10px; border-radius:50%; flex:0 0 auto; background:var(--cy-info); }
.status-dot.success { background:var(--cy-success); } .status-dot.warning { background:var(--cy-warning); }
.status-card-content { min-width:0; } .status-card-label { color:var(--cy-text-muted); font-size:12px; }
.status-card-value { color:var(--cy-text); font-weight:600; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.business-grid,.config-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; padding-top:12px; }
.settings-card,.operation-card { border-radius:var(--cy-radius-xl)!important; }
.card-title { font-size:16px; font-weight:600; } .group-description { color:var(--cy-text-muted); font-size:13px; margin:0 0 16px; }
.card-footer { display:flex; justify-content:flex-end; border-top:1px solid var(--cy-border-light); padding-top:14px; }
.section-alert { margin:12px 0 18px; } .operation-actions { display:flex; align-items:center; gap:14px; }
.confirm-label { margin:12px 0; color:var(--cy-text-secondary); } code { color:var(--cy-warning); }
@media (max-width:1199px) { .status-overview { grid-template-columns:repeat(3,minmax(0,1fr)); } }
@media (max-width:900px) { .business-grid,.config-grid { grid-template-columns:1fr; } }
</style>
