<template>
  <div>
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-header-title">版本与更新日志</h2>
        <p class="page-header-subtitle">image-service 独立版本线（自 v1.0.0 起，数据与后端 /health 同一事实源）</p>
      </div>
    </div>

    <n-spin :show="loading">
      <template v-if="versionInfo">
        <!-- 当前运行版本 -->
        <div class="current-version-card">
          <div class="cv-main">
            <div class="cv-version-row">
              <span class="cv-version">{{ versionInfo.version }}</span>
              <n-tag :type="statusTagType(versionInfo.version_status)" size="small" :bordered="false">
                {{ statusLabel(versionInfo.version_status) }}
              </n-tag>
              <n-tag type="info" size="small" :bordered="false" round>
                {{ versionInfo.version_line || 'image-service' }}
              </n-tag>
            </div>
            <p class="cv-compat">接口兼容口径：{{ versionInfo.api_compat || '-' }}（旧 4.x 客户端无需升级即可继续使用）</p>
          </div>
          <div class="cv-meta">
            <div class="cv-meta-item">
              <span class="cv-meta-label">运行环境</span>
              <span class="cv-meta-value">
                <n-tag :type="versionInfo.environment === 'production' ? 'success' : 'warning'" size="small" :bordered="false">
                  {{ versionInfo.environment === 'production' ? '生产环境' : versionInfo.environment === 'development' ? '开发环境' : versionInfo.environment }}
                </n-tag>
              </span>
            </div>
            <div class="cv-meta-item">
              <span class="cv-meta-label">构建提交</span>
              <span class="cv-meta-value mono">{{ versionInfo.build_commit || '未记录' }}</span>
            </div>
            <div class="cv-meta-item">
              <span class="cv-meta-label">构建时间</span>
              <span class="cv-meta-value mono">{{ versionInfo.build_time || '未记录' }}</span>
            </div>
          </div>
        </div>

        <!-- 版本日志 -->
        <div class="version-log-list">
          <div v-for="entry in versionInfo.version_log" :key="entry.version" class="version-entry">
            <div class="version-entry-head">
              <span class="version-entry-version">{{ entry.version }}</span>
              <n-tag :type="statusTagType(entry.status)" size="small" :bordered="false">
                {{ statusLabel(entry.status) }}
              </n-tag>
              <span class="version-entry-date">{{ entry.date }}</span>
            </div>
            <div v-if="entry.features && entry.features.length" class="version-section">
              <div class="version-section-title">新增功能</div>
              <ul class="version-section-list">
                <li v-for="(item, i) in entry.features" :key="'f' + i">{{ item }}</li>
              </ul>
            </div>
            <div v-if="entry.fixes && entry.fixes.length" class="version-section">
              <div class="version-section-title">修复内容</div>
              <ul class="version-section-list">
                <li v-for="(item, i) in entry.fixes" :key="'x' + i">{{ item }}</li>
              </ul>
            </div>
            <div v-if="entry.notes && entry.notes.length" class="version-section">
              <div class="version-section-title">升级注意事项</div>
              <ul class="version-section-list notes">
                <li v-for="(item, i) in entry.notes" :key="'n' + i">{{ item }}</li>
              </ul>
            </div>
          </div>
          <n-empty v-if="!versionInfo.version_log || !versionInfo.version_log.length" description="暂无版本日志" />
        </div>
      </template>
      <n-empty v-else-if="!loading" description="版本信息加载失败，请刷新重试" />
    </n-spin>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import http from '../api/http'

const message = useMessage()
const loading = ref(false)
const versionInfo = ref(null)

// 日志内容一律纯文本插值渲染，不做任何 HTML 解释，杜绝脚本注入
const statusLabels = {
  released: '已发布',
  pending_release: '待验收 / 待发布',
}
const statusTagTypes = {
  released: 'success',
  pending_release: 'warning',
}

function statusLabel(status) {
  return statusLabels[status] || status || '-'
}

function statusTagType(status) {
  return statusTagTypes[status] || 'default'
}

onMounted(async () => {
  loading.value = true
  try {
    const { data } = await http.get('/api/admin/version')
    versionInfo.value = data
  } catch (e) {
    message.error(e.response?.data?.detail || '加载版本信息失败')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.current-version-card {
  display: flex;
  align-items: stretch;
  gap: 24px;
  flex-wrap: wrap;
  background: var(--cy-bg-surface);
  border: 1px solid var(--cy-border-light);
  border-radius: var(--cy-radius);
  padding: 20px 24px;
  margin-bottom: 24px;
}

.cv-main {
  flex: 1;
  min-width: 260px;
}

.cv-version-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.cv-version {
  font-size: 28px;
  font-weight: 700;
  font-family: var(--cy-font-mono);
  color: var(--cy-text);
}

.cv-compat {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--cy-text-muted);
}

.cv-meta {
  display: flex;
  align-items: center;
  gap: 32px;
  flex-wrap: wrap;
}

.cv-meta-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cv-meta-label {
  font-size: 12px;
  color: var(--cy-text-muted);
}

.cv-meta-value {
  font-size: 14px;
  color: var(--cy-text);
}

.cv-meta-value.mono {
  font-family: var(--cy-font-mono);
}

.version-log-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.version-entry {
  background: var(--cy-bg-surface);
  border: 1px solid var(--cy-border-light);
  border-radius: var(--cy-radius);
  padding: 18px 22px;
}

.version-entry-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.version-entry-version {
  font-size: 18px;
  font-weight: 700;
  font-family: var(--cy-font-mono);
  color: var(--cy-text);
}

.version-entry-date {
  font-size: 13px;
  color: var(--cy-text-muted);
  margin-left: auto;
}

.version-section {
  margin-top: 10px;
}

.version-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--cy-text);
  margin-bottom: 6px;
}

.version-section-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--cy-text-muted);
  line-height: 1.7;
}

.version-section-list.notes li {
  color: var(--cy-warning);
}

@media (max-width: 768px) {
  .current-version-card {
    flex-direction: column;
    gap: 16px;
  }
}
</style>
