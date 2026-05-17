<template>
  <div>
    <div class="page-header">
      <h2 class="page-header-title">系统配置</h2>
      <div class="page-header-actions">
        <n-button size="small" :loading="loading" @click="loadConfig">刷新</n-button>
      </div>
    </div>

    <div class="config-grid">
      <n-card v-for="cat in categories" :key="cat.icon" :bordered="false" class="config-card">
        <div class="config-card-header">
          <span class="config-card-icon">{{ iconEmoji[cat.icon] }}</span>
          <h3 class="config-card-title">{{ cat.label }}</h3>
        </div>
        <n-form label-placement="left" label-width="160" :show-feedback="false" size="small">
          <n-form-item v-for="item in cat.items" :key="item.key" :label="item.description">
            <n-input v-if="item.field_type === 'password'"
              v-model:value="formValues[item.key]"
              type="password"
              show-password-on="click"
              :placeholder="item.is_sensitive ? '未修改则留空' : ''"
            />
            <n-input-number v-else-if="item.field_type === 'number'"
              v-model:value="formValues[item.key]"
              :precision="2"
              style="width: 100%"
            />
            <n-switch v-else-if="item.field_type === 'boolean'"
              v-model:value="formValues[item.key]"
            />
            <n-input v-else
              v-model:value="formValues[item.key]"
            />
          </n-form-item>
        </n-form>
        <div class="config-card-footer">
          <n-button type="primary" size="small" :loading="saving[cat.icon]" @click="saveCategory(cat)">
            保存
          </n-button>
        </div>
      </n-card>
    </div>

    <n-card :bordered="false" class="config-card restart-card">
      <div class="config-card-header">
        <span class="config-card-icon">🔄</span>
        <h3 class="config-card-title">容器管理</h3>
      </div>
      <n-alert type="warning" :bordered="false" style="margin-bottom: 16px">
        重启后端容器将导致服务短暂中断（约 5-10 秒）。修改 .env 配置后需重启才能完全生效。
      </n-alert>
      <n-button type="warning" :loading="restarting" @click="confirmRestart">
        重启后端容器
      </n-button>
      <div v-if="restartStatus" class="restart-status" :class="restartStatus">
        {{ restartMessages[restartStatus] }}
      </div>
    </n-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import http from '../api/http'

const msg = useMessage()
const dialog = useDialog()
const loading = ref(false)
const categories = ref([])
const formValues = reactive({})
const saving = reactive({})
const restarting = ref(false)
const restartStatus = ref(null)

const iconEmoji = {
  database: '🗄️',
  security: '🔐',
  wechat: '💳',
  smtp: '📧',
  payment: '💰',
  server: '🌐',
}

const restartMessages = {
  restarting: '容器正在重启...',
  healthy: '服务已恢复',
  failed: '服务恢复超时，请手动检查',
}

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

function confirmRestart() {
  dialog.warning({
    title: '确认重启',
    content: '重启后端容器将导致所有服务短暂中断（约 5-10 秒），确认继续？',
    positiveText: '确认重启',
    negativeText: '取消',
    onPositiveClick: doRestart,
  })
}

async function doRestart() {
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
  border-radius: 10px !important;
}

.config-card :deep(.n-card__content) {
  padding: 20px !important;
}

.config-card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--cy-border);
}

.config-card-icon {
  font-size: 18px;
}

.config-card-title {
  font-family: 'DM Sans', sans-serif;
  font-size: 15px;
  font-weight: 600;
  color: var(--cy-text);
  margin: 0;
}

.config-card-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--cy-border);
}

.restart-card {
  border-color: var(--cy-warning) !important;
  border-width: 1px !important;
}

.restart-status {
  margin-top: 12px;
  font-size: 13px;
  font-family: 'Space Mono', monospace;
}

.restart-status.restarting { color: var(--cy-warning); }
.restart-status.healthy { color: var(--cy-accent); }
.restart-status.failed { color: var(--cy-danger); }
</style>