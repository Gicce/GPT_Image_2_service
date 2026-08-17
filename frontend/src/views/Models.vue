<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">Image2 配置</h2>
        <p class="page-header-subtitle">唯一模型 gpt-image-2 的展示与按次计费参数</p>
      </div>
    </div>

    <n-empty
      v-if="loaded && !cfg.exists"
      description="Image2 配置不存在，请检查后端初始化数据"
      size="large"
      style="margin-top:60px"
    />

    <n-card v-else :bordered="false" class="form-card">
      <div class="form-card-header">
        <h3 class="form-card-title">模型与计费</h3>
        <p class="form-card-desc">模型 ID / 计费方式 / 币种为系统固定值，不可修改</p>
      </div>

      <n-form label-placement="left" label-width="120" :show-feedback="false">
        <n-form-item label="模型 ID">
          <n-input :value="cfg.model_id" readonly style="font-family:var(--cy-font-mono)" />
        </n-form-item>
        <n-form-item label="显示名称">
          <n-input v-model:value="form.display_name" placeholder="如 Image2" />
        </n-form-item>
        <n-form-item label="供应商">
          <n-input v-model:value="form.provider" placeholder="如 OpenAI" />
        </n-form-item>
        <n-form-item label="计费方式">
          <n-input value="按次（per call）" readonly />
        </n-form-item>
        <n-form-item label="单次价格 (USD)">
          <n-input
            v-model:value="form.price"
            placeholder="如 0.046，最多 6 位小数"
            :status="priceError ? 'error' : undefined"
            style="font-family:var(--cy-font-mono)"
          />
        </n-form-item>
        <n-form-item label="币种">
          <n-input value="USD" readonly />
        </n-form-item>
        <n-form-item label="启用模型">
          <n-switch v-model:value="form.is_enabled">
            <template #checked>启用</template>
            <template #unchecked>停用</template>
          </n-switch>
        </n-form-item>
        <n-form-item label="允许试用">
          <n-switch v-model:value="form.trial_allowed">
            <template #checked>允许</template>
            <template #unchecked>禁止</template>
          </n-switch>
        </n-form-item>
      </n-form>

      <div class="form-card-footer">
        <span v-if="priceError" class="price-error">{{ priceError }}</span>
        <n-button type="primary" :loading="saving" @click="save">保存配置</n-button>
      </div>
    </n-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import http from '../api/http'

const msg = useMessage()
const loaded = ref(false)
const saving = ref(false)
const cfg = ref({ exists: false })
const form = ref({
  display_name: '',
  provider: '',
  price: '',
  is_enabled: true,
  trial_allowed: false,
})

// 价格校验：必须为正数，最多 6 位小数；允许 0.07 / 0.075 / 0.070000
const priceError = computed(() => {
  const raw = (form.value.price ?? '').trim()
  if (!raw) return null // 空值不在输入时实时报错，提交时校验
  if (!/^\d+(\.\d{1,6})?$/.test(raw)) return '价格必须为数字，最多 6 位小数'
  if (Number(raw) <= 0) return '价格必须大于 0'
  return null
})

async function load() {
  try {
    const { data } = await http.get('/api/admin/image2-config')
    cfg.value = data
    if (data.exists) {
      form.value = {
        display_name: data.display_name || '',
        provider: data.provider || '',
        price: data.price_per_call_usd != null ? String(data.price_per_call_usd) : '',
        is_enabled: !!data.enabled,
        trial_allowed: !!data.trial_enabled,
      }
    }
  } catch (e) {
    msg.error(e.response?.data?.detail || '加载 Image2 配置失败')
  } finally {
    loaded.value = true
  }
}

async function save() {
  const raw = (form.value.price ?? '').trim()
  if (!raw) { msg.warning('请输入单次价格'); return }
  if (priceError.value) { msg.warning(priceError.value); return }
  if (!form.value.display_name.trim()) { msg.warning('请输入显示名称'); return }

  saving.value = true
  try {
    const body = {
      display_name: form.value.display_name.trim(),
      provider: form.value.provider.trim(),
      is_enabled: form.value.is_enabled,
      trial_allowed: form.value.trial_allowed,
      price_per_call_usd: raw, // 字符串原样传，保留小数位
    }
    const { data } = await http.put('/api/admin/image2-config', body)
    const changedKeys = Object.keys(data.changed || {})
    if (changedKeys.length) {
      msg.success(`保存成功（已更新: ${changedKeys.join(', ')}）`)
    } else {
      msg.success('保存成功（无变更）')
    }
    await load()
  } catch (e) {
    msg.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.form-card {
  background: var(--cy-bg-elevated) !important;
  border: 1px solid var(--cy-border) !important;
  border-radius: var(--cy-radius-lg) !important;
  max-width: 640px;
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
.form-card-desc {
  font-size: 12px;
  color: var(--cy-text-muted);
  margin-top: 4px;
}
.form-card :deep(.n-form-item) {
  margin-bottom: 18px;
}
.form-card-footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  padding-top: 16px;
  border-top: 1px solid var(--cy-border-light);
}
.price-error {
  font-size: 13px;
  color: var(--cy-danger);
}
</style>
