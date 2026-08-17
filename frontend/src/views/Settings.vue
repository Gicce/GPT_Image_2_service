<template>
  <div>
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">系统配置</h2>
        <p class="page-header-subtitle">管理服务端运行参数、支付配置、安全配置与运行状态</p>
      </div>
      <div class="page-header-actions">
        <n-button size="small" :loading="loading" @click="loadConfig">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
            </svg>
          </template>
          刷新
        </n-button>
        <n-button size="small" @click="checkEnvironment">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M19.35 10.04A7.49 7.49 0 0012 4C9.11 4 6.6 5.64 5.35 8.04A5.994 5.994 0 000 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM19 18H6c-2.21 0-4-1.79-4-4s1.79-4 4-4h.71C7.37 7.69 9.48 6 12 6c3.04 0 5.5 2.46 5.5 5.5v.5H19c1.66 0 3 1.34 3 3s-1.34 3-3 3z"/>
            </svg>
          </template>
          环境检查
        </n-button>
      </div>
    </div>

    <!-- 状态总览卡片 -->
    <div class="status-overview">
      <div class="status-card">
        <div class="status-card-icon" style="background: var(--cy-warning-bg); color: var(--cy-warning);">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
          </svg>
        </div>
        <div class="status-card-content">
          <div class="status-card-label">当前环境</div>
          <n-tag :type="envStatus.type" size="small" :bordered="false" round>
            {{ envStatus.label }}
          </n-tag>
        </div>
      </div>

      <div class="status-card">
        <div class="status-card-icon" style="background: var(--cy-success-bg); color: var(--cy-success);">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M20 4H4c-1.11 0-1.99.89-1.99 2L2 18c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V6c0-1.11-.89-2-2-2zm0 14H4v-6h16v6zm0-10H4V6h16v2z"/>
          </svg>
        </div>
        <div class="status-card-content">
          <div class="status-card-label">微信支付</div>
          <n-tag :type="wechatStatus.type" size="small" :bordered="false" round>
            {{ wechatStatus.label }}
          </n-tag>
        </div>
      </div>

      <div class="status-card">
        <div class="status-card-icon" style="background: var(--cy-info-bg); color: var(--cy-info);">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z"/>
          </svg>
        </div>
        <div class="status-card-content">
          <div class="status-card-label">Runtime Token</div>
          <n-tag :type="runtimeTokenStatus.type" size="small" :bordered="false" round>
            {{ runtimeTokenStatus.label }}
          </n-tag>
        </div>
      </div>

      <div class="status-card">
        <div class="status-card-icon" style="background: var(--cy-success-bg); color: var(--cy-success);">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
          </svg>
        </div>
        <div class="status-card-content">
          <div class="status-card-label">服务状态</div>
          <n-tag type="success" size="small" :bordered="false" round>
            <template #icon>
              <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--cy-success);margin-right:4px;"></span>
            </template>
            在线
          </n-tag>
        </div>
      </div>
    </div>

    <!-- 配置分组卡片 -->
    <div class="config-grid">
      <n-card v-for="cat in categories" :key="cat.icon" class="config-card" :bordered="true">
        <template #header>
          <div class="config-card-header">
            <div class="config-card-icon" :style="{ background: categoryColors[cat.icon]?.bg, color: categoryColors[cat.icon]?.color }">
              <component :is="categoryIcons[cat.icon]" />
            </div>
            <div class="config-card-title-wrap">
              <h3 class="config-card-title">{{ categoryTitles[cat.icon] || cat.label }}</h3>
              <p class="config-card-desc">{{ categoryDescriptions[cat.icon] || '' }}</p>
            </div>
          </div>
        </template>

        <n-form label-placement="left" label-width="140" :show-feedback="false" size="medium">
          <n-form-item v-for="item in cat.items" :key="item.key" :label="item.description">
            <n-input v-if="item.field_type === 'password'"
              v-model:value="formValues[item.key]"
              type="password"
              show-password-on="click"
              :placeholder="item.is_sensitive ? '未修改则留空' : '请输入'"
              clearable
            />
            <n-input-number v-else-if="item.field_type === 'number'"
              v-model:value="formValues[item.key]"
              :precision="2"
              style="width: 100%"
              placeholder="请输入"
            />
            <n-switch v-else-if="item.field_type === 'boolean'"
              v-model:value="formValues[item.key]"
            />
            <n-input v-else
              v-model:value="formValues[item.key]"
              :placeholder="item.value ? '已配置' : '未配置'"
              clearable
            />
          </n-form-item>
        </n-form>

        <template #footer>
          <div class="config-card-footer">
            <n-button type="primary" size="small" :loading="saving[cat.icon]" @click="saveCategory(cat)">
              保存配置
            </n-button>
          </div>
        </template>
      </n-card>
    </div>

    <!-- 运维操作卡片 -->
    <n-card class="operation-card" :bordered="true">
      <template #header>
        <div class="config-card-header">
          <div class="config-card-icon" style="background: var(--cy-warning-bg); color: var(--cy-warning);">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
            </svg>
          </div>
          <div class="config-card-title-wrap">
            <h3 class="config-card-title">运维操作</h3>
            <p class="config-card-desc">管理后端服务重启与维护操作</p>
          </div>
        </div>
      </template>

      <n-alert type="warning" :bordered="false" style="margin-bottom: 20px">
        <template #icon>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
          </svg>
        </template>
        重启后端服务会导致服务短暂中断，通常持续 5-10 秒。请确认没有正在进行的关键支付、订单分配或配置保存操作。
      </n-alert>

      <div class="operation-actions">
        <n-button type="warning" :loading="restarting" @click="showRestartDialog">
          <template #icon>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
            </svg>
          </template>
          重启后端服务
        </n-button>

        <div v-if="restartStatus" class="restart-status" :class="restartStatus">
          <span class="restart-status-icon">
            <svg v-if="restartStatus === 'restarting'" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" class="spinning">
              <path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46A7.93 7.93 0 0020 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74A7.93 7.93 0 004 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/>
            </svg>
            <svg v-else-if="restartStatus === 'healthy'" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
            </svg>
            <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2zm5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12 17 15.59z"/>
            </svg>
          </span>
          {{ restartMessages[restartStatus] }}
        </div>
      </div>
    </n-card>

    <!-- 重启确认对话框 -->
    <n-modal v-model:show="restartModalVisible" preset="dialog" title="确认重启后端服务">
      <div class="restart-modal-content">
        <n-alert type="warning" :bordered="false" style="margin-bottom: 20px">
          该操作会短暂中断服务，并可能影响正在进行的支付回调和用户操作。
        </n-alert>

        <div class="restart-confirm-input">
          <p class="restart-confirm-label">请输入 <code>RESTART</code> 以确认操作：</p>
          <n-input v-model:value="restartConfirmText" placeholder="请输入 RESTART" size="large" />
        </div>
      </div>

      <template #action>
        <div class="restart-modal-actions">
          <n-button @click="restartModalVisible = false">取消</n-button>
          <n-button type="warning" :disabled="restartConfirmText !== 'RESTART'" :loading="restarting" @click="doRestart">
            确认重启
          </n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, h, defineComponent } from 'vue'
import { useMessage } from 'naive-ui'
import http from '../api/http'

const msg = useMessage()
const loading = ref(false)
const categories = ref([])
const formValues = reactive({})
const saving = reactive({})
const restarting = ref(false)
const restartStatus = ref(null)
const restartModalVisible = ref(false)
const restartConfirmText = ref('')

// 分类标题映射
const categoryTitles = {
  database: '基础服务',
  security: '认证与安全',
  wechat: '微信支付',
  smtp: '邮件服务',
  payment: '支付限额',
  server: 'AI Runtime Token',
}

// 分类描述映射
const categoryDescriptions = {
  database: '数据库连接与基础服务配置',
  security: 'JWT 认证与管理员账户配置',
  wechat: '微信支付商户配置',
  smtp: 'SMTP 邮件服务配置',
  payment: '支付金额限制设置',
  server: 'AI 服务 Token 与 Base URL 配置',
}

// 分类颜色映射
const categoryColors = {
  database: { bg: 'var(--cy-info-bg)', color: 'var(--cy-info)' },
  security: { bg: 'var(--danger-bg)', color: 'var(--cy-danger)' },
  wechat: { bg: 'var(--cy-success-bg)', color: 'var(--cy-success)' },
  smtp: { bg: 'var(--cy-warning-bg)', color: 'var(--cy-warning)' },
  payment: { bg: 'var(--cy-primary-light)', color: 'var(--cy-primary)' },
  server: { bg: 'var(--cy-info-bg)', color: 'var(--cy-info)' },
}

// 分类图标组件
const categoryIcons = {
  database: defineComponent({
    render: () => h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'currentColor' }, [
      h('path', { d: 'M12 3C7.58 3 4 4.79 4 7v10c0 2.21 3.58 4 8 4s8-1.79 8-4V7c0-2.21-3.58-4-8-4zm0 2c3.87 0 6 1.27 6 2s-2.13 2-6 2-6-1.27-6-2 2.13-2 6-2zm6 12c0 .73-2.13 2-6 2s-6-1.27-6-2v-2.23c1.61.78 3.72 1.23 6 1.23s4.39-.45 6-1.23V17zm0-5c0 .73-2.13 2-6 2s-6-1.27-6-2V9.77c1.61.78 3.72 1.23 6 1.23s4.39-.45 6-1.23V12z' })
    ])
  }),
  security: defineComponent({
    render: () => h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'currentColor' }, [
      h('path', { d: 'M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z' })
    ])
  }),
  wechat: defineComponent({
    render: () => h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'currentColor' }, [
      h('path', { d: 'M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.89-2-2-2zm0 14H4V8l8 5 8-5v10zm-8-7L4 6h16l-8 5z' })
    ])
  }),
  smtp: defineComponent({
    render: () => h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'currentColor' }, [
      h('path', { d: 'M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z' })
    ])
  }),
  payment: defineComponent({
    render: () => h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'currentColor' }, [
      h('path', { d: 'M11.8 10.8c-2.27-.31-3-.84-3-1.88 0-1.02 1.01-1.76 2.7-1.76 1.78 0 2.68.77 2.78 2h2.09c-.12-2.12-1.6-3.37-4.18-3.79L12 4h-1.2l.19 2.35C8.27 6.76 6.7 8.08 6.7 10c0 2.02 1.5 3.24 4.7 3.75l-.19-2.35c2.27.31 3 .84 3 1.88 0 1.02-1.01 1.76-2.7 1.76-1.78 0-2.68-.77-2.78-2H6.64c.12 2.12 1.6 3.37 4.18 3.79L10.8 20H12l-.19-2.35c2.73-.41 4.3-1.73 4.3-3.65 0-2.02-1.5-3.24-4.7-3.75l.39 2.55zM12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z' })
    ])
  }),
  server: defineComponent({
    render: () => h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'currentColor' }, [
      h('path', { d: 'M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z' })
    ])
  }),
}

const restartMessages = {
  restarting: '容器正在重启，请稍候...',
  healthy: '服务已恢复正常',
  failed: '服务恢复超时，请手动检查',
}

// 环境状态
const envStatus = computed(() => {
  const env = import.meta.env.MODE
  if (env === 'production') {
    return { type: 'success', label: '生产环境' }
  }
  return { type: 'warning', label: '开发环境' }
})

// 微信支付状态（键名与后端 .env 一致）
const wechatStatus = computed(() => {
  const hasMchId = formValues['WECHAT_MCHID'] && formValues['WECHAT_MCHID'].length > 0
  const hasAppId = formValues['WECHAT_APPID'] && formValues['WECHAT_APPID'].length > 0
  const hasApiV3Key = formValues['WECHAT_APIV3_KEY'] && formValues['WECHAT_APIV3_KEY'].length > 0

  if (hasMchId && hasAppId && hasApiV3Key) {
    return { type: 'success', label: '已配置' }
  }
  return { type: 'warning', label: '未配置' }
})

// Runtime Token 状态（Image2 上游 Master Token，统一 Token 池）
const runtimeTokenStatus = computed(() => {
  const token = formValues['PACKYAPI_IMAGE_MASTER_TOKEN']
  if (token && token.length > 0) {
    return { type: 'success', label: '已配置' }
  }
  return { type: 'warning', label: '未配置' }
})

onMounted(() => loadConfig())

async function loadConfig() {
  loading.value = true
  try {
    const { data } = await http.get('/api/admin/config')
    categories.value = data.categories
    for (const cat of data.categories) {
      saving[cat.icon] = false
      for (const item of cat.items) {
        if (item.field_type === 'boolean') {
          formValues[item.key] = item.value === 'true' || item.value === 'True' || item.value === '1'
        } else if (item.field_type === 'number') {
          formValues[item.key] = parseFloat(item.value) || 0
        } else {
          formValues[item.key] = item.value
        }
      }
    }
  } catch {
    msg.error('加载配置失败')
  } finally {
    loading.value = false
  }
}

async function saveCategory(cat) {
  saving[cat.icon] = true
  const updates = {}
  for (const item of cat.items) {
    let val = formValues[item.key]
    if (item.field_type === 'boolean') {
      val = val ? 'true' : 'false'
    } else if (item.field_type === 'number') {
      val = String(val)
    }
    if (item.is_sensitive && !val) {
      continue
    }
    updates[item.key] = val
  }
  try {
    const { data } = await http.put('/api/admin/config', { updates })
    msg.success(`已更新: ${data.updated_keys.join(', ') || '无变更'}`)
  } catch {
    msg.error('保存失败')
  } finally {
    saving[cat.icon] = false
  }
}

function checkEnvironment() {
  const issues = []

  if (!formValues['WECHAT_MCHID']) issues.push('微信支付商户号未配置')
  if (!formValues['PACKYAPI_IMAGE_MASTER_TOKEN']) issues.push('Runtime Token 未配置')

  if (issues.length === 0) {
    msg.success('环境检查通过，所有关键配置已完成')
  } else {
    msg.warning(`环境检查发现问题：${issues.join('、')}`)
  }
}

function showRestartDialog() {
  restartConfirmText.value = ''
  restartModalVisible.value = true
}

async function doRestart() {
  if (restartConfirmText.value !== 'RESTART') return

  restartModalVisible.value = false
  restarting.value = true
  restartStatus.value = 'restarting'

  try {
    await http.post('/api/admin/config/restart')
  } catch {
    // Expected: connection lost during restart
  }

  // Poll health endpoint
  for (let i = 0; i < 15; i++) {
    await new Promise(r => setTimeout(r, 2000))
    try {
      await http.get('/health')
      restartStatus.value = 'healthy'
      msg.success('服务已恢复')
      break
    } catch {
      if (i === 14) {
        restartStatus.value = 'failed'
        msg.error('服务恢复超时，请手动检查')
      }
    }
  }
  restarting.value = false
}
</script>

<style scoped>
/* 状态总览 */
.status-overview {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

@media (max-width: 1200px) {
  .status-overview {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .status-overview {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 480px) {
  .status-overview {
    grid-template-columns: 1fr;
  }
}

.status-card {
  background: var(--cy-bg-elevated);
  border: 1px solid var(--cy-border);
  border-radius: var(--cy-radius-lg);
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  transition: all 0.2s;
}

.status-card:hover {
  border-color: var(--cy-border-dark);
  box-shadow: var(--cy-shadow);
}

.status-card-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--cy-radius);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.status-card-content {
  flex: 1;
  min-width: 0;
}

.status-card-label {
  font-size: 13px;
  color: var(--cy-text-muted);
  margin-bottom: 6px;
}

/* 配置卡片网格 */
.config-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
  margin-bottom: 20px;
}

@media (max-width: 900px) {
  .config-grid {
    grid-template-columns: 1fr;
  }
}

.config-card {
  background: var(--cy-bg-elevated) !important;
  border: 1px solid var(--cy-border) !important;
  border-radius: var(--cy-radius-xl) !important;
  box-shadow: var(--cy-shadow-sm) !important;
}

.config-card :deep(.n-card-header) {
  padding: 20px 20px 0 !important;
}

.config-card :deep(.n-card__content) {
  padding: 20px !important;
}

.config-card :deep(.n-card-footer) {
  padding: 0 20px 20px !important;
}

.config-card-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.config-card-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--cy-radius);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.config-card-title-wrap {
  flex: 1;
}

.config-card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--cy-text);
  margin: 0;
}

.config-card-desc {
  font-size: 12px;
  color: var(--cy-text-muted);
  margin: 4px 0 0;
}

.config-card-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
  border-top: 1px solid var(--cy-border-light);
  margin-top: 8px;
}

/* 运维操作卡片 */
.operation-card {
  background: var(--cy-bg-elevated) !important;
  border: 1px solid var(--cy-border) !important;
  border-radius: var(--cy-radius-xl) !important;
  box-shadow: var(--cy-shadow-sm) !important;
}

.operation-card :deep(.n-card-header) {
  padding: 20px 20px 0 !important;
}

.operation-card :deep(.n-card__content) {
  padding: 20px !important;
}

.operation-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}

.restart-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  padding: 8px 16px;
  border-radius: var(--cy-radius);
}

.restart-status.restarting {
  background: var(--cy-warning-bg);
  color: var(--cy-warning);
}

.restart-status.healthy {
  background: var(--cy-success-bg);
  color: var(--cy-success);
}

.restart-status.failed {
  background: var(--cy-danger-bg);
  color: var(--cy-danger);
}

.restart-status-icon {
  display: flex;
  align-items: center;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 重启对话框 */
.restart-modal-content {
  padding: 8px 0;
}

.restart-confirm-input {
  margin-top: 8px;
}

.restart-confirm-label {
  font-size: 14px;
  color: var(--cy-text-secondary);
  margin-bottom: 12px;
}

.restart-confirm-label code {
  background: var(--cy-bg-muted);
  padding: 2px 8px;
  border-radius: 4px;
  font-family: var(--cy-font-mono);
  color: var(--cy-warning);
}

.restart-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

/* 表单项样式 */
.config-card :deep(.n-form-item) {
  margin-bottom: 16px;
}

.config-card :deep(.n-form-item:last-child) {
  margin-bottom: 0;
}

.config-card :deep(.n-input),
.config-card :deep(.n-input-number) {
  width: 100%;
}
</style>
