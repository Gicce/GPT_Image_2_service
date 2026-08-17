<template>
  <div>
    <div class="page-header">
      <h2 class="page-header-title">在线客户端</h2>
      <n-button type="primary" size="small" @click="loadDevices" :loading="loading">
        <template #icon>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M17.65 6.35A7.958 7.958 0 0012 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0112 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
          </svg>
        </template>
        刷新
      </n-button>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#00d4aa,#00d4aa00)"></div>
        <div class="stat-card-label">在线设备</div>
        <div class="stat-card-value">{{ devices.length }}</div>
      </div>
    </div>

    <n-empty v-if="!loading && devices.length === 0" description="暂无在线客户端" size="large" style="margin-top:60px">
      <template #extra>
        <span style="color:var(--cy-text-dim);font-size:13px">客户端登录后会自动上报在线状态</span>
      </template>
    </n-empty>

    <n-data-table
      v-else
      :columns="columns"
      :data="devices"
      :loading="loading"
      :pagination="{ pageSize: 20 }"
      :row-key="row => row.device_id"
      :bordered="false"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, h } from 'vue'
import { NTag, NTooltip } from 'naive-ui'
import http from '../api/http'

const devices = ref([])
const loading = ref(false)
let refreshTimer = null

const columns = [
  {
    title: '用户',
    key: 'user_email',
    width: 180,
    render: row => row.user_email || row.user_id || '-'
  },
  {
    title: '设备名',
    key: 'device_name',
    width: 140,
    render: row => row.device_name || '-'
  },
  {
    title: '设备 ID',
    key: 'device_id',
    width: 160,
    render: row => {
      const id = row.device_id || ''
      if (id.length <= 12) return id
      const masked = id.slice(0, 8) + '...' + id.slice(-4)
      return h(NTooltip, { trigger: 'hover' }, {
        trigger: () => h('span', { style: 'font-family:var(--cy-font-mono);font-size:12px;cursor:pointer' }, masked),
        default: () => id
      })
    }
  },
  {
    title: '版本',
    key: 'app_version',
    width: 80,
    render: row => row.app_version || '-'
  },
  {
    title: '平台',
    key: 'platform',
    width: 80,
    render: row => {
      const platform = row.platform || '-'
      const platformIcons = {
        windows: '🪟',
        macos: '🍎',
        linux: '🐧',
        darwin: '🍎',
      }
      const icon = platformIcons[platform.toLowerCase()] || ''
      return `${icon} ${platform}`.trim()
    }
  },
  {
    title: 'IP',
    key: 'ip',
    width: 120,
    render: row => row.ip || '-'
  },
  {
    title: '最后心跳',
    key: 'last_seen',
    width: 160,
    render: row => {
      if (!row.last_seen) return '-'
      const date = new Date(row.last_seen)
      const now = new Date()
      const diff = Math.floor((now - date) / 1000)
      if (diff < 60) return `${diff} 秒前`
      if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
      return date.toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    }
  },
  {
    title: '状态',
    key: 'status',
    width: 80,
    render: () => h(NTag, { type: 'success', size: 'small', bordered: false }, { default: () => '在线' })
  },
]

async function loadDevices() {
  loading.value = true
  try {
    const { data } = await http.get('/api/admin/online-devices')
    devices.value = data.devices || []
  } catch (e) {
    console.error('Failed to load online devices:', e)
    devices.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadDevices()
  // Auto refresh every 60 seconds
  refreshTimer = setInterval(loadDevices, 60000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<style scoped>
.stats-row {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  position: relative;
  background: #fff;
  border-radius: var(--cy-radius);
  border: 1px solid var(--cy-border);
  padding: 20px 24px;
  min-width: 180px;
  overflow: hidden;
}

.stat-card-accent {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
}

.stat-card-label {
  font-size: 13px;
  color: var(--cy-text-muted);
  margin-bottom: 4px;
}

.stat-card-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--cy-text);
  font-family: var(--cy-font-mono);
}
</style>
