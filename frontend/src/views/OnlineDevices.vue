<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">客户端设备</h2>
        <p v-if="lastUpdatedAt" class="page-header-subtitle">最后更新：{{ lastUpdatedAt }}（相对时间由服务器时钟计算）</p>
      </div>
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
        <div class="stat-card-label">当前在线</div>
        <div class="stat-card-value">{{ onlineCount }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-card-accent" style="background:linear-gradient(90deg,#0f766e,#0f766e00)"></div>
        <div class="stat-card-label">历史设备</div>
        <div class="stat-card-value">{{ historyCount }}</div>
      </div>
    </div>

    <div class="filter-bar">
      <n-radio-group v-model:value="statusFilter" size="small" @update:value="loadDevices">
        <n-radio-button value="all">全部</n-radio-button>
        <n-radio-button value="online">在线</n-radio-button>
        <n-radio-button value="offline">离线</n-radio-button>
      </n-radio-group>
    </div>

    <n-empty v-if="!loading && devices.length === 0" description="暂无设备记录" size="large" style="margin-top:60px">
      <template #extra>
        <span style="color:var(--cy-text-dim);font-size:13px">客户端登录后会自动上报心跳，设备历史永久保留</span>
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
const statusFilter = ref('all')
const onlineCount = ref(0)
const historyCount = ref(0)
let refreshTimer = null

// 相对时间一律用服务器下发的 seconds_since_seen（恒 >= 0），
// 禁止用浏览器本地 new Date() 求差——服务器与管理员浏览器时钟偏移会透出负数
function formatSecondsAgo(seconds) {
  if (seconds == null) return '-'
  if (seconds < 60) return `${seconds} 秒前`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  return `${Math.floor(seconds / 86400)} 天前`
}

function formatDateTime(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

const columns = [
  {
    title: '用户',
    key: 'user_email',
    width: 180,
    render: row => row.user_email || row.username || row.user_id || '-'
  },
  {
    title: '设备名',
    key: 'device_name',
    width: 130,
    render: row => row.device_name || '-'
  },
  {
    title: '设备 ID',
    key: 'device_id',
    width: 150,
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
    key: 'client_version',
    width: 80,
    render: row => row.client_version || '-'
  },
  {
    title: '平台',
    key: 'platform',
    width: 80,
    render: row => {
      const platform = row.platform || '-'
      const platformIcons = { windows: '🪟', macos: '🍎', linux: '🐧', darwin: '🍎' }
      const icon = platformIcons[platform.toLowerCase()] || ''
      return `${icon} ${platform}`.trim()
    }
  },
  {
    title: 'IP',
    key: 'last_ip',
    width: 120,
    render: row => row.last_ip || '-'
  },
  {
    title: '首次出现',
    key: 'first_seen_at',
    width: 160,
    render: row => formatDateTime(row.first_seen_at)
  },
  {
    title: '最后心跳',
    key: 'seconds_since_seen',
    width: 110,
    render: row => formatSecondsAgo(row.seconds_since_seen)
  },
  {
    title: '心跳次数',
    key: 'heartbeat_count',
    width: 90,
    render: row => row.heartbeat_count ?? '-'
  },
  {
    title: '状态',
    key: 'status',
    width: 80,
    render: row => h(NTag, {
      type: row.online ? 'success' : 'default',
      size: 'small',
      bordered: false,
    }, { default: () => row.online ? '在线' : '离线' })
  },
]

const lastUpdatedAt = ref('')

async function loadDevices() {
  loading.value = true
  try {
    const params = {}
    if (statusFilter.value !== 'all') params.status = statusFilter.value
    const { data } = await http.get('/api/admin/devices', { params })
    devices.value = data.devices || []
    onlineCount.value = data.online_count ?? 0
    historyCount.value = data.history_count ?? devices.value.length
    if (data.generated_at) {
      lastUpdatedAt.value = new Date(data.generated_at).toLocaleTimeString('zh-CN', { hour12: false })
    }
  } catch (e) {
    console.error('Failed to load devices:', e)
    devices.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadDevices()
  // 页面自身按 30s 刷新列表（与客户端 60s 心跳上报是两件独立的事）
  refreshTimer = setInterval(loadDevices, 30000)
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

.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
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
