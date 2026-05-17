<template>
  <div class="login-page">
    <div class="login-bg-pattern"></div>
    <div class="login-container">
      <div class="login-brand">
        <div class="login-logo">
          <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
            <rect x="2" y="2" width="32" height="32" rx="8" stroke="#00d4aa" stroke-width="2" fill="#00d4aa1a"/>
            <path d="M12 18L16 22L24 14" stroke="#00d4aa" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <h1 class="login-title">CyImagePro</h1>
        <p class="login-subtitle">管理后台</p>
      </div>
      <n-card class="login-card" :bordered="false">
        <div class="login-card-header">
          <h2 class="login-card-title">管理员登录</h2>
          <p class="login-card-desc">请输入您的管理员凭据</p>
        </div>
        <n-form @submit.prevent="login" label-placement="top">
          <n-form-item label="用户名">
            <n-input v-model:value="form.username" placeholder="请输入用户名" size="large" />
          </n-form-item>
          <n-form-item label="密码">
            <n-input v-model:value="form.password" type="password" placeholder="请输入密码" size="large" show-password-on="click" />
          </n-form-item>
          <n-button type="primary" block attr-type="submit" :loading="loading" size="large" class="login-btn">登录</n-button>
        </n-form>
      </n-card>
      <p class="login-footer">CyImagePro v1.0 &middot; AI Image & Chat API Platform</p>
    </div>
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

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0e0e16;
  position: relative;
  overflow: hidden;
}

.login-bg-pattern {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 600px 400px at 20% 50%, #00d4aa0d 0%, transparent 70%),
    radial-gradient(ellipse 500px 300px at 80% 30%, #6366f10a 0%, transparent 70%),
    radial-gradient(ellipse 400px 400px at 60% 80%, #00d4aa08 0%, transparent 70%);
  animation: bgShift 20s ease-in-out infinite alternate;
}

@keyframes bgShift {
  0% { opacity: 0.6; transform: scale(1); }
  100% { opacity: 1; transform: scale(1.05); }
}

.login-container {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24px;
  width: 100%;
  max-width: 400px;
  padding: 0 20px;
}

.login-brand {
  text-align: center;
  margin-bottom: 4px;
}

.login-logo {
  margin-bottom: 12px;
  animation: logoPulse 3s ease-in-out infinite;
}

@keyframes logoPulse {
  0%, 100% { filter: drop-shadow(0 0 8px #00d4aa44); }
  50% { filter: drop-shadow(0 0 16px #00d4aa66); }
}

.login-title {
  font-family: 'Space Mono', monospace;
  font-size: 28px;
  font-weight: 700;
  color: #e4e4ef;
  letter-spacing: -0.02em;
}

.login-subtitle {
  font-size: 14px;
  color: #8888a0;
  margin-top: 4px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.login-card {
  width: 100%;
  background: #1e1e2e !important;
  border: 1px solid #2a2a3e !important;
  border-radius: 12px !important;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.4), 0 0 0 1px #2a2a3e;
}

.login-card :deep(.n-card__content) {
  padding: 28px 28px 24px !important;
}

.login-card-header {
  margin-bottom: 24px;
}

.login-card-title {
  font-size: 18px;
  font-weight: 600;
  color: #e4e4ef;
  margin-bottom: 6px;
}

.login-card-desc {
  font-size: 13px;
  color: #8888a0;
}

.login-btn {
  margin-top: 8px;
  height: 44px;
  font-weight: 600;
  font-size: 15px;
  letter-spacing: 0.02em;
  border-radius: 8px !important;
  box-shadow: 0 4px 16px #00d4aa33;
  transition: box-shadow 0.3s, transform 0.15s;
}

.login-btn:hover {
  box-shadow: 0 6px 24px #00d4aa55;
  transform: translateY(-1px);
}

.login-btn:active {
  transform: translateY(0);
}

.login-footer {
  font-size: 12px;
  color: #5c5c72;
  letter-spacing: 0.02em;
}
</style>