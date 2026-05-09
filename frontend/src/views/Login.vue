<template>
  <div style="height:100vh;display:flex;align-items:center;justify-content:center;background:#1a1a1a">
    <n-card style="width:360px" title="管理员登录">
      <n-form @submit.prevent="login">
        <n-form-item label="用户名">
          <n-input v-model:value="form.username" placeholder="admin" />
        </n-form-item>
        <n-form-item label="密码">
          <n-input v-model:value="form.password" type="password" placeholder="••••••" />
        </n-form-item>
        <n-button type="primary" block attr-type="submit" :loading="loading">登录</n-button>
      </n-form>
    </n-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import http from '../api/http'

const router = useRouter()
const msg = useMessage()
const loading = ref(false)
const form = ref({ username: '', password: '' })

async function login() {
  loading.value = true
  try {
    const { data } = await http.post('/api/auth/admin/login', form.value)
    localStorage.setItem('admin_token', data.access_token)
    router.push('/dashboard')
  } catch {
    msg.error('账号或密码错误')
  } finally {
    loading.value = false
  }
}
</script>
