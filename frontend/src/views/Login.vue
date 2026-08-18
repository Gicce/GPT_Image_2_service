<template>
  <div class="login-page">
    <div class="login-bg-pattern"></div>
    <div class="login-container">
      <div class="login-brand">
        <div class="login-logo">
          <svg width="48" height="48" viewBox="0 0 40 40" fill="none">
            <!-- 主背景 -->
            <rect x="2" y="2" width="36" height="36" rx="10" fill="url(#loginBrandGrad)" />
            <!-- 云形装饰 -->
            <path d="M12 22c0-4 3-7 7-7 2.5 0 4.5 1.5 5.5 3.5 2.5-.5 4.5 1 4.5 3.5 0 2-1.5 3.5-3.5 3.5H14c-2.2 0-4-1.8-4-4v1z" fill="white" fill-opacity="0.9"/>
            <!-- 节点装饰 -->
            <circle cx="26" cy="16" r="3" fill="white" fill-opacity="0.95"/>
            <circle cx="30" cy="22" r="2" fill="white" fill-opacity="0.85"/>
            <defs>
              <linearGradient id="loginBrandGrad" x1="2" y1="2" x2="38" y2="38" gradientUnits="userSpaceOnUse">
                <stop stop-color="#00BFA6"/>
                <stop offset="1" stop-color="#0F766E"/>
              </linearGradient>
            </defs>
          </svg>
        </div>
        <h1 class="login-title">晨阳云枢</h1>
        <p class="login-title-en">CyCloudHub</p>
        <p class="login-subtitle">CyImagePro 云端运营与计费中枢</p>
      </div>
      <n-card class="login-card" :bordered="false">
        <div class="login-card-header">
          <h2 class="login-card-title">管理员登录</h2>
          <p class="login-card-desc">请输入您的管理员凭据</p>
        </div>
        <n-form @submit.prevent="login" label-placement="top">
          <n-form-item label="用户名">
            <n-input v-model:value="form.username" placeholder="请输入用户名" size="large" :disabled="loading" @keydown.enter.prevent="login" />
          </n-form-item>
          <n-form-item label="密码">
            <n-input ref="passwordInputRef" v-model:value="form.password" type="password" placeholder="请输入密码" size="large" show-password-on="click" :disabled="loading" @keydown.enter.prevent="login" />
          </n-form-item>
          <div v-if="loginError" class="login-error">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.5"/>
              <path d="M8 4.5v4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              <circle cx="8" cy="11.2" r="0.9" fill="currentColor"/>
            </svg>
            <span>{{ loginError }}</span>
          </div>
          <n-button type="primary" block attr-type="submit" :loading="loading" :disabled="loading || !form.username || !form.password" size="large" class="login-btn">
            {{ loading ? '正在登录...' : '登录' }}
          </n-button>
        </n-form>
      </n-card>
      <p class="login-footer">晨阳云枢 · CyCloudHub &middot; 企业级云端运营平台</p>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import http from '../api/http'

const router = useRouter()
const msg = useMessage()
const loading = ref(false)
const loginError = ref('')
const passwordInputRef = ref(null)
const form = ref({ username: '', password: '' })

async function login() {
  if (loading.value) return
  if (!form.value.username || !form.value.password) return
  loading.value = true
  loginError.value = ''
  try {
    const { data } = await http.post('/api/auth/admin/login', form.value)
    localStorage.setItem('admin_token', data.access_token)
    if (data.admin?.must_change_password) {
      msg.warning('管理员已重置您的密码，请先修改密码')
      router.push({ path: '/profile', query: { tab: 'password' } })
    } else {
      router.push('/dashboard')
    }
  } catch (err) {
    const status = err.response?.status
    if (status === 401) {
      loginError.value = '用户名或密码错误'
    } else if (status === 429) {
      loginError.value = '尝试次数过多，请稍后再试'
    } else if (!err.response) {
      loginError.value = '无法连接服务器，请检查网络'
    } else {
      loginError.value = '服务暂时不可用，请稍后重试'
    }
    // 失败后清空密码、保留用户名并聚焦密码框，便于快速重试
    form.value.password = ''
    nextTick(() => passwordInputRef.value?.focus())
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
  background: linear-gradient(135deg, #F6F8FB 0%, #EEF2F7 100%);
  position: relative;
  overflow: hidden;
}

.login-bg-pattern {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 600px 400px at 20% 50%, rgba(0, 191, 166, 0.06) 0%, transparent 70%),
    radial-gradient(ellipse 500px 300px at 80% 30%, rgba(59, 130, 246, 0.05) 0%, transparent 70%),
    radial-gradient(ellipse 400px 400px at 60% 80%, rgba(0, 191, 166, 0.04) 0%, transparent 70%);
}

.login-container {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24px;
  width: 100%;
  max-width: 420px;
  padding: 0 20px;
}

.login-brand {
  text-align: center;
  margin-bottom: 8px;
}

.login-logo {
  margin-bottom: 16px;
  filter: drop-shadow(0 4px 12px rgba(0, 191, 166, 0.2));
}

.login-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--cy-text);
  letter-spacing: -0.02em;
  margin: 0 0 4px;
}

.login-title-en {
  font-size: 14px;
  font-weight: 600;
  color: var(--cy-primary);
  letter-spacing: 0.05em;
  margin: 0 0 8px;
}

.login-subtitle {
  font-size: 13px;
  color: var(--cy-text-muted);
  margin: 0;
}

.login-card {
  width: 100%;
  background: #FFFFFF !important;
  border: 1px solid var(--cy-border) !important;
  border-radius: 16px !important;
  box-shadow: 0 8px 32px rgba(15, 23, 42, 0.08), 0 0 0 1px var(--cy-border);
}

.login-card :deep(.n-card__content) {
  padding: 32px 32px 28px !important;
}

.login-card-header {
  margin-bottom: 24px;
}

.login-card-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--cy-text);
  margin: 0 0 6px;
}

.login-card-desc {
  font-size: 13px;
  color: var(--cy-text-muted);
  margin: 0;
}

.login-btn {
  margin-top: 8px;
  height: 44px;
  font-weight: 600;
  font-size: 15px;
  letter-spacing: 0.02em;
  border-radius: 8px !important;
  box-shadow: 0 4px 16px rgba(0, 191, 166, 0.25);
  transition: all 0.2s;
}

.login-btn:hover {
  box-shadow: 0 6px 24px rgba(0, 191, 166, 0.35);
  transform: translateY(-1px);
}

.login-btn:active {
  transform: translateY(0);
}

.login-error {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: #DC2626;
  font-size: 13px;
  line-height: 1.4;
}

.login-error svg {
  flex-shrink: 0;
  margin-top: 1px;
}

.login-footer {
  font-size: 12px;
  color: var(--cy-text-dim);
  letter-spacing: 0.02em;
}
</style>
