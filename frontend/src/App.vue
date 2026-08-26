<template>
  <n-config-provider :theme="null" :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-dialog-provider>
        <router-view />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
// 使用浅色主题 (null = light theme)
const themeOverrides = {
  common: {
    // 主色系统
    primaryColor: '#00BFA6',
    primaryColorHover: '#14D8B4',
    primaryColorPressed: '#0F766E',
    primaryColorSuppl: '#00BFA6',

    // 字体
    fontFamily: '"Inter", "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, sans-serif',
    fontFamilyMono: '"SF Mono", "Consolas", monospace',

    // 圆角
    borderRadius: '8px',
    borderRadiusSmall: '6px',

    // 文字颜色
    textColorBase: '#1F2937',
    textColor1: '#1F2937',
    textColor2: '#475569',
    textColor3: '#64748B',
    textColor4: '#94A3B8',

    // 背景色
    bodyColor: '#F6F8FB',
    cardColor: '#FFFFFF',
    modalColor: '#FFFFFF',
    popoverColor: '#FFFFFF',
    tableColor: '#FFFFFF',

    // 边框色
    borderColor: '#E5E7EB',
    dividerColor: '#EEF2F7',

    // 成功/警告/错误/信息
    successColor: '#10B981',
    warningColor: '#F59E0B',
    errorColor: '#EF4444',
    infoColor: '#3B82F6',

    // 输入框
    inputColor: '#FFFFFF',
    inputColorDisabled: '#F1F5F9',
    placeholderColor: '#94A3B8',

    // 按钮
    actionColor: '#F1F5F9',
    hoverColor: 'rgba(0, 191, 166, 0.08)',
    pressedColor: 'rgba(0, 191, 166, 0.12)',
  },
  Button: {
    borderRadiusMedium: '8px',
    borderRadiusSmall: '6px',
    textColorPrimary: '#FFFFFF',
    textColorHoverPrimary: '#FFFFFF',
    textColorPressedPrimary: '#FFFFFF',
    fontWeight: '500',
    fontWeightStrong: '600',
    paddingMedium: '0 16px',
    heightMedium: '36px',
    heightLarge: '40px',
  },
  Card: {
    borderRadius: '14px',
    color: '#FFFFFF',
    borderColor: '#E5E7EB',
    titleFontSizeSmall: '15px',
    titleFontSizeMedium: '16px',
    titleFontSizeLarge: '18px',
    titleFontWeight: '600',
    paddingMedium: '20px',
    paddingLarge: '24px',
  },
  Input: {
    borderRadius: '8px',
    color: '#FFFFFF',
    borderColor: '#E5E7EB',
    borderHover: '#00BFA6',
    borderFocus: '#00BFA6',
    boxShadowFocus: '0 0 0 3px rgba(0, 191, 166, 0.1)',
    textColor: '#1F2937',
    placeholderColor: '#94A3B8',
    heightMedium: '36px',
    paddingMedium: '0 12px',
  },
  Select: {
    borderRadius: '8px',
    peers: {
      InternalSelection: {
        borderRadius: '8px',
        textColor: '#1F2937',
        borderColor: '#E5E7EB',
        borderHover: '#00BFA6',
        borderActive: '#00BFA6',
        boxShadowActive: '0 0 0 3px rgba(0, 191, 166, 0.1)',
      }
    }
  },
  Menu: {
    borderRadius: '8px',
    itemColorActive: '#E6FFFA',
    itemColorActiveHover: '#CCFFF5',
    itemColorHover: '#F1F5F9',
    itemTextColorActive: '#00BFA6',
    itemTextColorActiveHover: '#00BFA6',
    itemTextColor: '#475569',
    itemTextColorHover: '#1F2937',
    itemIconColorActive: '#00BFA6',
    itemIconColorActiveHover: '#00BFA6',
    itemIconColor: '#64748B',
    itemIconColorHover: '#475569',
    arrowColor: '#94A3B8',
    fontSize: '14px',
    itemHeight: '40px',
  },
  Tag: {
    borderRadius: '6px',
  },
  Alert: {
    borderRadius: '8px',
    titleFontWeight: '600',
  },
  Dialog: {
    borderRadius: '14px',
  },
  DataTable: {
    borderRadius: '12px',
    thColor: '#F8FAFC',
    tdColor: '#FFFFFF',
    borderColor: '#E5E7EB',
    thTextColor: '#475569',
    tdTextColor: '#1F2937',
    thFontWeight: '600',
  },
  Layout: {
    color: '#F6F8FB',
    siderColor: '#FFFFFF',
    siderBorderColor: '#E5E7EB',
    headerColor: '#FFFFFF',
    headerBorderColor: '#E5E7EB',
  },
  Form: {
    labelFontSizeTopSmall: '13px',
    labelFontSizeTopMedium: '14px',
    labelFontSizeTopLarge: '15px',
    labelTextColor: '#475569',
    feedbackTextColorError: '#EF4444',
  },
  Message: {
    borderRadius: '8px',
  },
  Notification: {
    borderRadius: '12px',
  },
}
</script>

<style>
/* 企业级浅色主题 CSS 变量 */
:root {
  /* 主色 */
  --cy-primary: #00BFA6;
  --cy-primary-dark: #0F766E;
  --cy-primary-light: #E6FFFA;
  --cy-primary-hover: #14D8B4;

  /* 背景 */
  --cy-bg: #F6F8FB;
  --cy-bg-elevated: #FFFFFF;
  --cy-bg-surface: #F8FAFC;
  --cy-bg-muted: #F1F5F9;

  /* 边框 */
  --cy-border: #E5E7EB;
  --cy-border-light: #EEF2F7;
  --cy-border-dark: #D1D5DB;

  /* 文字 */
  --cy-text: #1F2937;
  --cy-text-secondary: #475569;
  --cy-text-muted: #64748B;
  --cy-text-dim: #94A3B8;

  /* 状态色 */
  --cy-success: #10B981;
  --cy-warning: #F59E0B;
  --cy-danger: #EF4444;
  --cy-info: #3B82F6;

  /* 状态背景 */
  --cy-success-bg: #ECFDF5;
  --cy-warning-bg: #FFFBEB;
  --cy-danger-bg: #FEF2F2;
  --cy-info-bg: #EFF6FF;

  /* 字体 */
  --cy-font: 'Inter', 'PingFang SC', 'Microsoft YaHei', system-ui, -apple-system, sans-serif;
  --cy-font-mono: 'SF Mono', 'Consolas', monospace;

  /* 阴影 */
  --cy-shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.04);
  --cy-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
  --cy-shadow-md: 0 8px 24px rgba(15, 23, 42, 0.06);
  --cy-shadow-lg: 0 12px 40px rgba(15, 23, 42, 0.08);

  /* 圆角 */
  --cy-radius-sm: 6px;
  --cy-radius: 8px;
  --cy-radius-md: 12px;
  --cy-radius-lg: 14px;
  --cy-radius-xl: 16px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: var(--cy-font);
  background: var(--cy-bg);
  color: var(--cy-text);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  line-height: 1.5;
}

/* 页面头部通用样式 */
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--cy-border-light);
}

.page-header-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.page-header-title {
  font-family: var(--cy-font);
  font-size: 22px;
  font-weight: 700;
  color: var(--cy-text);
  letter-spacing: -0.02em;
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-header-title::before {
  content: '';
  display: inline-block;
  width: 4px;
  height: 22px;
  background: var(--cy-primary);
  border-radius: 2px;
}

.page-header-subtitle {
  font-size: 14px;
  color: var(--cy-text-muted);
  margin-left: 16px;
}

.page-header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

/* 统计卡片 */
.stat-card {
  background: var(--cy-bg-elevated);
  border: 1px solid var(--cy-border);
  border-radius: var(--cy-radius-lg);
  padding: 20px 24px;
  position: relative;
  overflow: hidden;
  transition: all 0.2s ease;
}

.stat-card:hover {
  border-color: var(--cy-border-dark);
  box-shadow: var(--cy-shadow-md);
}

.stat-card-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--cy-radius);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
}

.stat-card-label {
  font-size: 13px;
  color: var(--cy-text-muted);
  font-weight: 500;
  margin-bottom: 8px;
  letter-spacing: 0.01em;
}

.stat-card-value {
  font-family: var(--cy-font-mono);
  font-size: 28px;
  font-weight: 700;
  color: var(--cy-text);
  letter-spacing: -0.02em;
}

/* 滚动条 */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--cy-border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--cy-border-dark); }

/* 链接样式 */
a {
  color: var(--cy-primary);
  text-decoration: none;
  transition: color 0.2s;
}

a:hover {
  color: var(--cy-primary-hover);
}

/* 选中文本 */
::selection {
  background: var(--cy-primary-light);
  color: var(--cy-primary-dark);
}

/* 所有管理弹窗都受当前视口约束，内容区滚动而不是撑出屏幕。 */
.n-card.n-modal {
  max-width: calc(100vw - 48px);
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
}

.n-card.n-modal > .n-card-content {
  min-height: 0;
  overflow: auto;
}
</style>
