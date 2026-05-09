<template>
  <n-layout style="height:100vh">
    <n-layout-header style="padding:0 24px;height:56px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #2e2e2e">
      <span style="font-size:18px;font-weight:600;color:#ececec">CyImagePro 管理后台</span>
      <n-button text @click="logout" style="color:#8e8ea0">退出登录</n-button>
    </n-layout-header>
    <n-layout has-sider style="height:calc(100vh - 56px)">
      <n-layout-sider width="200" bordered>
        <n-menu :options="menuOptions" :value="activeKey" @update:value="navigate" />
      </n-layout-sider>
      <n-layout-content style="padding:24px;overflow:auto">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { h } from 'vue'

const router = useRouter()
const route = useRoute()
const activeKey = computed(() => route.path.replace('/', ''))

const menuOptions = [
  { label: '概览', key: 'dashboard' },
  { label: 'Token 库存', key: 'tokens' },
  { label: '通知栏', key: 'notice' },
  { label: '提示词库', key: 'prompts' },
  { label: '模型管理', key: 'models' },
  { label: '订单管理', key: 'orders' },
  { label: '用户管理', key: 'users' },
]

function navigate(key) { router.push('/' + key) }
function logout() {
  localStorage.removeItem('admin_token')
  router.push('/login')
}
</script>
