<template>
  <div>
    <n-h2>通知栏</n-h2>
    <n-card>
      <n-form-item label="通知内容（留空则不显示跑马灯）">
        <n-input v-model:value="content" type="textarea" :rows="4" placeholder="输入要广播给所有客户端的通知文字..." />
      </n-form-item>
      <n-button type="primary" :loading="loading" @click="save">保存并推送</n-button>
      <n-text depth="3" style="margin-left:12px;font-size:12px">客户端每 3 分钟自动拉取一次</n-text>
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
