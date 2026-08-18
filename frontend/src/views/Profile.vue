<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">个人设置</h2>
        <p class="page-header-subtitle">当前登录的管理员账户信息</p>
      </div>
    </div>

    <n-grid :cols="2" :x-gap="16" responsive="screen" item-responsive>
      <n-grid-item span="2 m:2 l:1">
        <n-card title="账户信息" :bordered="false">
          <n-descriptions :column="1" bordered label-placement="left" size="small">
            <n-descriptions-item label="用户名">{{ profile.username || '-' }}</n-descriptions-item>
            <n-descriptions-item label="显示名称">{{ profile.display_name || '-' }}</n-descriptions-item>
            <n-descriptions-item label="角色">
              <n-tag :type="profile.role === 'super_admin' ? 'warning' : 'info'" size="small" :bordered="false">
                {{ profile.role }}
              </n-tag>
            </n-descriptions-item>
            <n-descriptions-item label="最后登录">{{ formatTime(profile.last_login_at) }}</n-descriptions-item>
            <n-descriptions-item label="密码修改时间">{{ formatTime(profile.password_changed_at) }}</n-descriptions-item>
            <n-descriptions-item label="创建时间">{{ formatTime(profile.created_at) }}</n-descriptions-item>
          </n-descriptions>
        </n-card>
      </n-grid-item>
      <n-grid-item span="2 m:2 l:1">
        <n-card title="修改密码" :bordered="false">
          <n-alert v-if="profile.must_change_password" type="warning" :bordered="false" style="margin-bottom:16px">
            管理员已重置您的密码，请立即修改为新密码后继续使用。
          </n-alert>
          <n-form label-placement="top">
            <n-form-item label="当前密码" required>
              <n-input v-model:value="pwdForm.current_password" type="password" show-password-on="click" />
            </n-form-item>
            <n-form-item label="新密码" required>
              <n-input v-model:value="pwdForm.new_password" type="password" show-password-on="click"
                       placeholder="至少 10 位" />
            </n-form-item>
            <n-form-item label="确认新密码" required>
              <n-input v-model:value="pwdForm.confirm" type="password" show-password-on="click" />
            </n-form-item>
          </n-form>
          <n-space justify="end">
            <n-button type="primary" :loading="saving" :disabled="!pwdForm.current_password || !pwdForm.new_password" @click="changePassword">
              修改密码
            </n-button>
          </n-space>
        </n-card>
      </n-grid-item>
    </n-grid>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import http from '../api/http'

const msg = useMessage()
const router = useRouter()

const profile = ref({ must_change_password: false })
const pwdForm = ref({ current_password: '', new_password: '', confirm: '' })
const saving = ref(false)

function formatTime(iso) {
  if (!iso) return '-'
  try { return new Date(iso).toLocaleString('zh-CN', { hour12: false }) } catch { return iso }
}

async function loadProfile() {
  try {
    const { data } = await http.get('/api/admin/admins/me')
    profile.value = data
  } catch (e) {
    msg.error(e.response?.data?.detail || '加载账户信息失败')
  }
}

async function changePassword() {
  if (pwdForm.value.new_password !== pwdForm.value.confirm) {
    msg.error('两次输入的新密码不一致')
    return
  }
  saving.value = true
  try {
    const { data } = await http.put('/api/admin/admins/me/password', {
      current_password: pwdForm.value.current_password,
      new_password: pwdForm.value.new_password,
    })
    msg.success(data.message || '密码修改成功')
    pwdForm.value = { current_password: '', new_password: '', confirm: '' }
    // 密钥修改后引导重新登录
    dialogRelogin()
  } catch (e) {
    msg.error(e.response?.data?.detail || '修改失败')
  } finally {
    saving.value = false
  }
}

function dialogRelogin() {
  setTimeout(() => {
    localStorage.removeItem('admin_token')
    router.push('/login')
  }, 1500)
}

onMounted(() => {
  loadProfile()
})
</script>
