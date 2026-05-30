<template>
  <div>
    <div class="page-header">
      <h2 class="page-header-title">试用 Token 管理</h2>
    </div>

    <div class="stat-card" style="margin-bottom:20px">
      <div class="stat-card-accent" style="background:linear-gradient(90deg,#00d4aa,#00d4aa00)"></div>
      <div class="stat-card-label">image 试用 Token 可用库存</div>
      <div class="stat-card-value">{{ trialCount }}</div>
    </div>

    <n-card :bordered="false" class="form-card">
      <div class="form-card-header">
        <h3 class="form-card-title">批量录入试用 Token</h3>
      </div>
      <n-form-item label="Token 列表（每行一条）">
        <n-input v-model:value="tokensRaw" type="textarea" :rows="8" placeholder="每行粘贴一条，支持 '名称 sk-xxx' 格式，自动提取 sk- 开头的 Token" />
      </n-form-item>
      <n-button type="primary" :loading="loading" @click="submit">录入</n-button>
    </n-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import http from '../api/http'

const msg = useMessage()
const loading = ref(false)
const trialCount = ref(0)
const tokensRaw = ref('')

async function loadStock() {
  const { data } = await http.get('/api/admin/tokens/stock')
  trialCount.value = data.image?.trial ?? 0
}

async function submit() {
  const tokens = tokensRaw.value.split('\n').map(t => t.trim()).filter(Boolean)
  if (!tokens.length) return msg.warning('请输入至少一个 Token')
  loading.value = true
  try {
    const { data } = await http.post('/api/admin/tokens/batch', {
      tokens,
      group: 'image',
      is_trial: true,
    })
    msg.success(`成功录入 ${data.added} 个 Token`)
    tokensRaw.value = ''
    await loadStock()
  } catch (e) {
    msg.error(e.response?.data?.detail || '录入失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadStock)
</script>

<style scoped>
.form-card {
  background: var(--cy-bg-elevated) !important;
  border: 1px solid var(--cy-border) !important;
  border-radius: 10px !important;
}
.form-card :deep(.n-card__content) {
  padding: 24px !important;
}
.form-card-header {
  margin-bottom: 20px;
}
.form-card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--cy-text);
}
</style>