<template>
  <div>
    <n-h2>Token 库存</n-h2>
    <n-grid :cols="5" :x-gap="12" style="margin-bottom:24px">
      <n-gi v-for="(count, pkg) in stock" :key="pkg">
        <n-card :title="pkg === '1' ? '试用 Token' : `$${pkg} 套餐`">
          <n-statistic :value="count" label="剩余" />
        </n-card>
      </n-gi>
    </n-grid>

    <n-card title="批量录入 Token">
      <n-form-item label="套餐类型">
        <n-select v-model:value="form.package_usd" :options="pkgOptions" style="width:200px" />
      </n-form-item>
      <n-form-item label="是否试用 Token">
        <n-switch v-model:value="form.is_trial" />
      </n-form-item>
      <n-form-item label="Token 列表（每行一个）">
        <n-input v-model:value="form.tokens_raw" type="textarea" :rows="8" placeholder="每行粘贴一个 Token" />
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
const stock = ref({})
const form = ref({ package_usd: 10, is_trial: false, tokens_raw: '' })
const pkgOptions = [
  { label: '试用 ($1)', value: 1 },
  { label: '$10 套餐', value: 10 },
  { label: '$20 套餐', value: 20 },
  { label: '$50 套餐', value: 50 },
  { label: '$100 套餐', value: 100 },
]

async function loadStock() {
  const { data } = await http.get('/api/admin/tokens/stock')
  stock.value = data
}

async function submit() {
  const tokens = form.value.tokens_raw.split('\n').map(t => t.trim()).filter(Boolean)
  if (!tokens.length) return msg.warning('请输入至少一个 Token')
  loading.value = true
  try {
    const { data } = await http.post('/api/admin/tokens/batch', {
      tokens,
      package_usd: form.value.is_trial ? 1 : form.value.package_usd,
      is_trial: form.value.is_trial,
    })
    msg.success(`成功录入 ${data.added} 个 Token`)
    form.value.tokens_raw = ''
    await loadStock()
  } catch (e) {
    msg.error(e.response?.data?.detail || '录入失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadStock)
</script>
