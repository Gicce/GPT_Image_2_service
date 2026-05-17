<template>
  <div>
    <div class="page-header">
      <h2 class="page-header-title">通知栏</h2>
    </div>
    <n-card :bordered="false" class="form-card">
      <n-form-item label="通知内容（留空则不显示跑马灯）">
        <n-input v-model:value="content" type="textarea" :rows="4" placeholder="输入要广播给所有客户端的通知文字..." />
      </n-form-item>
      <div class="notice-footer">
        <n-button type="primary" :loading="loading" @click="save">保存并推送</n-button>
        <span class="notice-hint">客户端每 3 分钟自动拉取一次</span>
      </div>
    </n-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import http from '../api/http'

const msg = useMessage()
const loading = ref(false)
const content = ref('')

onMounted(async () => {
  const { data } = await http.get('/api/admin/notice')
  content.value = data.content
})

async function save() {
  loading.value = true
  try {
    await http.put('/api/admin/notice', { content: content.value })
    msg.success('通知已更新，客户端将在下次轮询时收到')
  } catch {
    msg.error('保存失败')
  } finally {
    loading.value = false
  }
}
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
.notice-footer {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 4px;
}
.notice-hint {
  font-size: 12px;
  color: var(--cy-text-dim);
}
</style>