<template>
  <n-layout style="height:100vh;background:var(--cy-bg)">
    <n-layout-header class="app-header">
      <div class="header-left">
        <div class="header-brand" @click="$router.push('/dashboard')">
          <svg width="24" height="24" viewBox="0 0 36 36" fill="none">
            <rect x="2" y="2" width="32" height="32" rx="8" stroke="#00d4aa" stroke-width="2" fill="#00d4aa1a"/>
            <path d="M12 18L16 22L24 14" stroke="#00d4aa" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span class="header-brand-text">CyImagePro</span>
        </div>
      </div>
      <div class="header-right">
        <div class="header-admin-badge">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="#00d4aa"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z"/></svg>
          <span>Admin</span>
        </div>
        <n-button text class="header-logout" @click="logout">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style="margin-right:4px"><path d="M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z"/></svg>
          退出登录
        </n-button>
      </div>
    </n-layout-header>
    <n-layout has-sider style="height:calc(100vh - 52px)">
      <n-layout-sider class="app-sider" :width="220" :native-scrollbar="false" bordered>
        <div class="sider-inner">
          <n-menu :options="menuOptions" :value="activeKey" @update:value="navigate" :indent="20" />
        </div>
      </n-layout-sider>
      <n-layout-content class="app-content" :native-scrollbar="false">
        <div class="content-wrapper">
          <router-view />
        </div>
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup>
import { computed, h, defineComponent } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NIcon } from 'naive-ui'

const router = useRouter()
const route = useRoute()
const activeKey = computed(() => route.path.replace('/', ''))

const iconMap = {
  dashboard: 'M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z',
  tokens: 'M20 6h-4V4c0-1.1-.9-2-2-2h-4c-1.1 0-2 .9-2 2v2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-8-2h4v2h-4V4zM4 8h16v3H4V8zm0 12V13h5v2h6v-2h5v7H4z',
  notice: 'M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2zm-2 1H8v-6c0-2.48 1.51-4.5 4-4.5s4 2.02 4 4.5v6z',
  prompts: 'M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z',
  models: 'M9.4 16.6L4.8 12l4.6-4.6L8 6l-6 6 6 6 1.4-1.4zm5.2 0l4.6-4.6-4.6-4.6L16 6l6 6-6 6-1.4-1.4z',
  groups: 'M4 8h4V4H4v4zm6 12h4v-4h-4v4zm-6 0h4v-4H4v4zm0-6h4v-4H4v4zm6 0h4v-4h-4v4zm6-10v4h4V4h-4zm-6 4h4V4h-4v4zm6 6h4v-4h-4v4zm0 6h4v-4h-4v4z',
  orders: 'M18 17H6v-2h12v2zm0-4H6v-2h12v2zm0-4H6V7h12v2zM3 22l1.5-1.5L6 22l1.5-1.5L9 22l1.5-1.5L12 22l1.5-1.5L15 22l1.5-1.5L18 22l1.5-1.5L21 22V2l-1.5 1.5L18 2l-1.5 1.5L15 2l-1.5 1.5L12 2l-1.5 1.5L9 2 7.5 3.5 6 2 4.5 3.5 3 2v20z',
  users: 'M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z',
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

const menuOptions = [
  { label: '概览', key: 'dashboard', icon: makeIcon('dashboard') },
  { label: 'Token 库存', key: 'tokens', icon: makeIcon('tokens') },
  { label: '通知栏', key: 'notice', icon: makeIcon('notice') },
  { label: '提示词库', key: 'prompts', icon: makeIcon('prompts') },
  { label: '模型管理', key: 'models', icon: makeIcon('models') },
  { label: '分组管理', key: 'groups', icon: makeIcon('groups') },
  { label: '订单管理', key: 'orders', icon: makeIcon('orders') },
  { label: '用户管理', key: 'users', icon: makeIcon('users') },
  { label: '系统配置', key: 'settings', icon: makeIcon('settings') },
]

function navigate(key) { router.push('/' + key) }
function logout() {
  localStorage.removeItem('admin_token')
  router.push('/login')
}
</script>

<style scoped>
.app-header {
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: #1a1a28;
  border-bottom: 1px solid #2a2a3e;
  position: relative;
  z-index: 10;
}

.header-left {
  display: flex;
  align-items: center;
}

.header-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.header-brand:hover { opacity: 0.85; }

.header-brand-text {
  font-family: 'Space Mono', monospace;
  font-size: 16px;
  font-weight: 700;
  color: #e4e4ef;
  letter-spacing: -0.01em;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.header-admin-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #8888a0;
  padding: 4px 10px;
  background: #00d4aa0d;
  border: 1px solid #00d4aa22;
  border-radius: 6px;
}

.header-logout {
  font-size: 13px;
  color: #8888a0 !important;
  transition: color 0.2s;
  display: flex;
  align-items: center;
}

.header-logout:hover {
  color: #ff4466 !important;
}

.app-sider {
  background: #1a1a28 !important;
  border-right: 1px solid #2a2a3e !important;
}

.sider-inner {
  padding: 12px 8px;
}

.app-content {
  background: var(--cy-bg);
}

.content-wrapper {
  padding: 28px 32px;
  max-width: 1400px;
}
</style>