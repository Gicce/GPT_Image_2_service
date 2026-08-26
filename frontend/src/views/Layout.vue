<template>
  <n-layout style="height:100vh;background:var(--cy-bg)">
    <!-- 顶部栏 -->
    <n-layout-header class="app-header">
      <div class="header-left">
        <n-button class="sider-toggle" quaternary circle @click="collapsed = !collapsed" aria-label="切换导航">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </n-button>
        <div class="header-breadcrumb">
          <span class="breadcrumb-prefix">晨阳云枢</span>
          <span class="breadcrumb-sep">/</span>
          <span class="breadcrumb-current">{{ currentPageTitle }}</span>
        </div>
      </div>
      <div class="header-right">
        <n-tag :type="envTag.type" size="small" :bordered="false" round>
          {{ envTag.label }}
        </n-tag>
        <n-dropdown trigger="click" :options="adminMenuOptions" @select="onAdminMenuSelect">
          <div class="header-admin header-admin-clickable">
            <div class="admin-avatar">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z"/>
              </svg>
            </div>
            <span class="admin-name">{{ adminProfile.username || '管理员' }}</span>
            <svg class="admin-caret" width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
              <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
        </n-dropdown>
      </div>
    </n-layout-header>

    <n-layout has-sider style="height:calc(100vh - 60px)">
      <!-- 左侧导航 -->
      <n-layout-sider class="app-sider" :width="240" :collapsed-width="72" :collapsed="collapsed" :native-scrollbar="false" bordered>
        <div class="sider-brand">
          <div class="brand-logo">
            <svg width="32" height="32" viewBox="0 0 40 40" fill="none">
              <!-- 主背景 -->
              <rect x="2" y="2" width="36" height="36" rx="10" fill="url(#brandGrad)" />
              <!-- 云形装饰 -->
              <path d="M12 22c0-4 3-7 7-7 2.5 0 4.5 1.5 5.5 3.5 2.5-.5 4.5 1 4.5 3.5 0 2-1.5 3.5-3.5 3.5H14c-2.2 0-4-1.8-4-4v1z" fill="white" fill-opacity="0.9"/>
              <!-- 节点装饰 -->
              <circle cx="26" cy="16" r="3" fill="white" fill-opacity="0.95"/>
              <circle cx="30" cy="22" r="2" fill="white" fill-opacity="0.85"/>
              <defs>
                <linearGradient id="brandGrad" x1="2" y1="2" x2="38" y2="38" gradientUnits="userSpaceOnUse">
                  <stop stop-color="#00BFA6"/>
                  <stop offset="1" stop-color="#0F766E"/>
                </linearGradient>
              </defs>
            </svg>
          </div>
          <div v-if="!collapsed" class="brand-info">
            <div class="brand-name">晨阳云枢</div>
            <div class="brand-name-en">CyCloudHub</div>
            <div class="brand-tagline">云端运营与计费中枢</div>
          </div>
        </div>

        <div class="sider-menu">
          <n-menu
            :options="menuOptions"
            :value="activeKey"
            :collapsed="collapsed"
            :collapsed-width="72"
            :collapsed-icon-size="20"
            :default-expanded-keys="expandedGroups"
            :indent="18"
            @update:value="navigate"
          />
        </div>

        <div class="sider-footer">
          <div v-if="!collapsed" class="status-item">
            <span class="status-label">服务状态</span>
            <n-tag type="success" size="small" :bordered="false" round>
              <template #icon>
                <span class="status-dot"></span>
              </template>
              在线
            </n-tag>
          </div>
        </div>
      </n-layout-sider>

      <!-- 主内容区 -->
      <n-layout-content class="app-content" :native-scrollbar="false">
        <div class="content-wrapper">
          <router-view />
        </div>
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup>
import { computed, h, defineComponent, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NIcon } from 'naive-ui'
import http from '../api/http'

const router = useRouter()
const route = useRoute()
const activeKey = computed(() => route.path.replace('/', ''))

// 当前登录管理员（/api/admin/admins/me），用于右上角菜单与角色可见性
const adminProfile = ref({ username: '', display_name: '', role: '' })
const isSuperAdmin = computed(() => adminProfile.value.role === 'super_admin')
const collapsed = ref(window.innerWidth < 1200)
const expandedGroups = ['operations', 'finance', 'resources', 'system']

function syncCollapsed() {
  collapsed.value = window.innerWidth < 1200
}

onMounted(async () => {
  window.addEventListener('resize', syncCollapsed)
  try {
    const { data } = await http.get('/api/admin/admins/me')
    adminProfile.value = data
  } catch {
    // profile 拉取失败不影响导航；401 由全局拦截器处理
  }
})

onBeforeUnmount(() => window.removeEventListener('resize', syncCollapsed))

const adminMenuOptions = computed(() => [
  {
    key: 'account',
    label: `当前账户：${adminProfile.value.display_name || adminProfile.value.username || 'admin'}`,
    disabled: true,
  },
  { key: 'profile', label: '个人设置' },
  { key: 'change-password', label: '修改密码' },
  { type: 'divider', key: 'divider', props: {} },
  { key: 'logout', label: '退出登录' },
])

function onAdminMenuSelect(key) {
  if (key === 'profile' || key === 'change-password') {
    router.push({ path: '/profile', query: { tab: key === 'change-password' ? 'password' : 'info' } })
  } else if (key === 'logout') {
    logout()
  }
}

// 页面标题映射
const pageTitleMap = {
  dashboard: '概览',
  tokens: 'Token 库存',
  notice: '运营通知',
  models: 'Image2 配置',
  orders: '交易订单',
  users: '客户账户',
  transactions: '账务流水',
  'online-devices': '在线客户端',
  settings: '系统设置',
  admins: '管理员与登录',
  profile: '个人设置',
}

const currentPageTitle = computed(() => {
  const key = activeKey.value || 'dashboard'
  return pageTitleMap[key] || '概览'
})

// 环境标签
const envTag = computed(() => {
  const env = import.meta.env.MODE
  if (env === 'production') {
    return { type: 'success', label: '生产环境' }
  }
  return { type: 'warning', label: '开发环境' }
})

// 图标路径映射
const iconMap = {
  dashboard: 'M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z',
  tokens: 'M20 6h-4V4c0-1.1-.9-2-2-2h-4c-1.1 0-2 .9-2 2v2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-8-2h4v2h-4V4zM4 8h16v3H4V8zm0 12V13h5v2h6v-2h5v7H4z',
  notice: 'M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2zm-2 1H8v-6c0-2.48 1.51-4.5 4-4.5s4 2.02 4 4.5v6z',
  models: 'M9.4 16.6L4.8 12l4.6-4.6L8 6l-6 6 6 6 1.4-1.4zm5.2 0l4.6-4.6-4.6-4.6L16 6l6 6-6 6-1.4-1.4z',
  orders: 'M18 17H6v-2h12v2zm0-4H6v-2h12v2zm0-4H6V7h12v2zM3 22l1.5-1.5L6 22l1.5-1.5L9 22l1.5-1.5L12 22l1.5-1.5L15 22l1.5-1.5L18 22l1.5-1.5L21 22V2l-1.5 1.5L18 2l-1.5 1.5L15 2l-1.5 1.5L12 2l-1.5 1.5L9 2 7.5 3.5L6 2 4.5 3.5 3 2v20z',
  users: 'M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z',
  transactions: 'M11.8 10.9c-2.27-.31-3-.84-3-1.88 0-1.02 1.01-1.76 2.7-1.76 1.78 0 2.68.77 2.78 2h2.09c-.12-2.12-1.6-3.37-4.18-3.79L12 4h-1.2l.19 2.35C8.27 6.76 6.7 8.08 6.7 10c0 2.02 1.5 3.24 4.7 3.75l-.19-2.35c2.27.31 3 .84 3 1.88 0 1.02-1.01 1.76-2.7 1.76-1.78 0-2.68-.77-2.78-2H6.64c.12 2.12 1.6 3.37 4.18 3.79L10.8 20H12l-.19-2.35c2.73-.41 4.3-1.73 4.3-3.65 0-2.02-1.5-3.24-4.7-3.75l.39 2.55zM12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z',
  'online-devices': 'M4 6h18V4H4c-1.1 0-2 .9-2 2v11H0v3h14v-3H4V6zm19 2h-6c-.55 0-1 .45-1 1v12c0 .55.45 1 1 1h6c.55 0 1-.45 1-1V9c0-.55-.45-1-1-1zm-1 12h-4v-10h4v10z',
  settings: 'M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 00.12-.61l-1.92-3.32a.49.49 0 00-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 00-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.07.62-.07.94s.02.64.07.94l-2.03 1.58a.49.49 0 00-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z',
}

function makeIcon(key) {
  return defineComponent({
    render() {
      return h(NIcon, { size: 18 }, {
        default: () => h('svg', {
          xmlns: 'http://www.w3.org/2000/svg',
          viewBox: '0 0 24 24',
          fill: 'currentColor',
        }, [h('path', { d: iconMap[key] })])
      })
    }
  })
}

const menuOptions = computed(() => {
  const systemChildren = [
    { label: '系统设置', key: 'settings', icon: makeIcon('settings') },
  ]
  if (isSuperAdmin.value) {
    systemChildren.unshift({ label: '管理员与登录', key: 'admins', icon: makeIcon('users') })
  }
  return [
    { label: '概览', key: 'dashboard', icon: makeIcon('dashboard') },
    {
      label: '运营管理', key: 'operations', icon: makeIcon('users'),
      children: [
        { label: '客户账户', key: 'users', icon: makeIcon('users') },
        { label: '客户端设备', key: 'online-devices', icon: makeIcon('online-devices') },
        { label: '运营通知', key: 'notice', icon: makeIcon('notice') },
      ],
    },
    {
      label: '交易与财务', key: 'finance', icon: makeIcon('transactions'),
      children: [
        { label: '交易订单', key: 'orders', icon: makeIcon('orders') },
        { label: '账务流水', key: 'transactions', icon: makeIcon('transactions') },
        { label: '成本与毛利', key: 'margin', icon: makeIcon('transactions') },
      ],
    },
    {
      label: '资源与计费', key: 'resources', icon: makeIcon('tokens'),
      children: [
        { label: 'Image2 配置', key: 'models', icon: makeIcon('models') },
        { label: '定价规则', key: 'pricing', icon: makeIcon('models') },
        { label: 'Token 库存', key: 'tokens', icon: makeIcon('tokens') },
      ],
    },
    { label: '系统管理', key: 'system', icon: makeIcon('settings'), children: systemChildren },
  ]
})

function navigate(key) { router.push('/' + key) }

function logout() {
  localStorage.removeItem('admin_token')
  router.push('/login')
}
</script>

<style scoped>
/* 顶部栏 */
.app-header {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: #FFFFFF;
  border-bottom: 1px solid var(--cy-border);
  position: relative;
  z-index: 10;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sider-toggle {
  color: var(--cy-text-muted);
}

.header-breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.breadcrumb-prefix {
  color: var(--cy-text-muted);
  font-weight: 500;
}

.breadcrumb-sep {
  color: var(--cy-text-dim);
}

.breadcrumb-current {
  color: var(--cy-text);
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.header-admin {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--cy-bg-muted);
  border-radius: var(--cy-radius);
}

.header-admin-clickable {
  cursor: pointer;
  transition: background 0.2s;
  user-select: none;
}

.header-admin-clickable:hover {
  background: var(--cy-primary-light);
}

.admin-caret {
  color: var(--cy-text-dim);
}

.admin-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--cy-primary-light);
  color: var(--cy-primary);
  display: flex;
  align-items: center;
  justify-content: center;
}

.admin-name {
  font-size: 14px;
  color: var(--cy-text);
  font-weight: 500;
}

.header-logout {
  font-size: 14px;
  color: var(--cy-text-muted) !important;
  transition: color 0.2s;
  display: flex;
  align-items: center;
  padding: 6px 12px;
  border-radius: var(--cy-radius);
}

.header-logout:hover {
  color: var(--cy-danger) !important;
  background: var(--cy-danger-bg);
}

/* 左侧导航 */
.app-sider {
  background: #FFFFFF !important;
  border-right: 1px solid var(--cy-border) !important;
  display: flex;
  flex-direction: column;
  transition: width 0.2s ease;
}

.sider-brand {
  padding: 20px 16px;
  border-bottom: 1px solid var(--cy-border-light);
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 104px;
  overflow: hidden;
}

.brand-logo {
  flex-shrink: 0;
}

.brand-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.brand-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--cy-text);
  letter-spacing: -0.01em;
}

.brand-name-en {
  font-size: 12px;
  font-weight: 600;
  color: var(--cy-primary);
  letter-spacing: 0.02em;
}

.brand-tagline {
  font-size: 11px;
  color: var(--cy-text-dim);
  letter-spacing: 0.01em;
}

.sider-menu {
  flex: 1;
  padding: 12px 8px;
  overflow-y: auto;
}

.sider-footer {
  padding: 16px;
  border-top: 1px solid var(--cy-border-light);
}

.status-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.status-label {
  font-size: 13px;
  color: var(--cy-text-muted);
}

.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--cy-success);
  margin-right: 6px;
}

/* 主内容区 */
.app-content {
  background: var(--cy-bg);
  min-width: 0;
}

.content-wrapper {
  padding: 28px 32px;
  width: 100%;
  max-width: 1680px;
  min-width: 0;
  margin: 0 auto;
}

/* 响应式 */
@media (max-width: 1200px) {
  .content-wrapper {
    padding: 24px;
  }
}

@media (max-width: 1199px) {
  .app-header {
    padding: 0 16px;
  }

  .header-admin .admin-name {
    display: none;
  }

  .content-wrapper {
    padding: 20px 24px;
  }
}
</style>
