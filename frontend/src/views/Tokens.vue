<template>
  <div>
    <n-h2>试用 Token 管理</n-h2>

    <n-card title="sora 试用 Token 库存" style="margin-bottom:24px">
      <n-statistic :value="trialCount" label="可用试用 Token" />
    </n-card>

    <n-card title="批量录入试用 Token">
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
  trialCount.value = data.sora?.trial ?? 0
}

async function submit() {
  const tokens = tokensRaw.value.split('\n').map(t => t.trim()).filter(Boolean)
  if (!tokens.length) return msg.warning('请输入至少一个 Token')
  loading.value = true
  try {
    const { data } = await http.post('/api/admin/tokens/batch', {
      tokens,
      group: 'sora',
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
